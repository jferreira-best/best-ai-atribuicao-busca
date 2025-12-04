import os
import logging
from src.shared.llm import call_api_with_messages
from src.orchestrator import classifier
from src.search import rag_core
from src.shared import state_manager

# --- CONFIGURAÇÃO ---
# Link oficial para abertura de chamados
LINK_SISTEMA_CHAMADOS = "https://atendimento.educacao.sp.gov.br"

# --- Helpers ---
def _deduplicate_sources(source_list):
    """
    Limpa a fonte (remove '| Tipo: ...') e remove duplicatas.
    Ex: "Fonte: Arquivo.pdf | Tipo: Portaria" -> "Fonte: Arquivo.pdf"
    """
    if not source_list:
        return []
    
    seen = set()
    output = []
    
    for source in source_list:
        # Pega apenas a parte antes do PIPE (|) e remove espaços extras
        clean_source = source.split('|')[0].strip()
        
        if clean_source not in seen:
            output.append(clean_source)
            seen.add(clean_source)
            
    return output

def _load_prompt(filename):
    """
    Carrega o prompt procurando na pasta src/prompts relativo a este arquivo.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        src_dir = os.path.dirname(os.path.dirname(current_file_path))
        prompt_path = os.path.join(src_dir, "prompts", filename)
        prompt_path = os.path.normpath(prompt_path)

        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            logging.error(f"ARQUIVO NÃO EXISTE: {prompt_path}")
            # Fallback para raiz (caso o ambiente de execução mude)
            root_path = os.path.join(os.getcwd(), "prompts", filename)
            if os.path.exists(root_path):
                with open(root_path, "r", encoding="utf-8") as f:
                    return f.read()
            return f"Erro: Arquivo '{filename}' não encontrado."

    except Exception as e:
        logging.error(f"Erro crítico ao ler arquivo: {e}")
        return "Erro: Falha na leitura do template."

def _format_history(messages):
    if not messages:
        return "Nenhum histórico."
    formatted = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        formatted += f"{role.upper()}: {content}\n"
    return formatted

# --- Função Principal ---
def route_request(last_message: str, full_body: dict, client_ip: str):
    """
    Roteador Inteligente (Fast Track) com Estado, Deduplicação e Link Dinâmico
    """
    
    # 1. GERENCIAMENTO DE ESTADO
    session_id = full_body.get("session_id")
    raw_history = []
    
    if session_id:
        logging.info(f"SessionID: {session_id}. Buscando histórico...")
        # Recupera histórico do Azure Table Storage
        raw_history = state_manager.get_history(session_id)
    else:
        # Fallback: Histórico via JSON (para testes manuais sem sessão)
        raw_history = full_body.get("historico", [])

    history_text = _format_history(raw_history)

    # 2. Consultar o Router (LLM)
    router_template = _load_prompt("router_v2.md")
    
    if "Erro:" in router_template:
        return {"resposta": "Erro interno: Template router não encontrado.", "comando": "ERROR"}

    router_prompt = router_template.replace("{historico}", history_text).replace("{ultima_mensagem}", last_message)
    
    decision_cmd = "CMD_TECNICA"
    try:
        # LLM rápido decide o próximo passo
        msgs = [{"role": "system", "content": "Você é um roteador estrito."}, {"role": "user", "content": router_prompt}]
        _, _, llm_decision = call_api_with_messages(msgs, max_tokens=15, temperature=0.0)
        if llm_decision:
            decision_cmd = llm_decision.strip().upper()
    except Exception as e:
        logging.error(f"Erro LLM Router: {e}")

    logging.info(f"Router Decision: {decision_cmd} | IP: {client_ip}")

    # 3. Executar Decisão
    response_text = ""
    source_docs = []

    if decision_cmd == "CMD_TECNICA":
        # Classifica para saber qual prompt técnico usar (Avaliação, Classificação ou Alocação)
        intent_data = classifier.classify_intent(last_message)
        modulo = intent_data.get("modulo", "fora_escopo")
        
        if modulo == "fora_escopo":
             response_text = _load_prompt("templates/fora_escopo.md")
        else:
             # Executa o RAG
             context_docs = rag_core.retrieve_context(last_message)
             context_text = "\n\n".join([f"{d['content']} (Fonte: {d['meta']})" for d in context_docs])
             
             # Carrega o prompt do módulo específico
             tech_filename = f"technical/{modulo}.md"
             tech_prompt = _load_prompt(tech_filename)
             
             if "Erro:" in tech_prompt:
                 # Fallback seguro
                 tech_prompt = _load_prompt("base_agent.md")

             if "Erro:" in tech_prompt:
                 response_text = "Erro interno: Prompt técnico não encontrado."
             else:
                 # Monta e executa o prompt final
                 final_sys_prompt = tech_prompt.replace("{contexto}", context_text)\
                                               .replace("{sub_intencao}", intent_data.get("sub_intencao", "geral"))\
                                               .replace("{emocao}", "neutro")
                 
                 rag_msgs = [{"role": "system", "content": final_sys_prompt}, {"role": "user", "content": last_message}]
                 _, _, response_text = call_api_with_messages(rag_msgs, max_tokens=800, temperature=0.3)
                 source_docs = context_docs

    elif decision_cmd == "CMD_ESCOLA":
        response_text = _load_prompt("templates/escola.md")
        
    elif decision_cmd == "CMD_REGIONAL":
        response_text = _load_prompt("templates/regional.md")
        
    elif decision_cmd == "CMD_CHAMADO":
        tpl = _load_prompt("templates/chamado.md")
        # Injeta o link real no template
        response_text = tpl.replace("[Inserir Link do Portal de Chamados Aqui]", LINK_SISTEMA_CHAMADOS)

    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")
        
    else: 
        response_text = _load_prompt("templates/fora_escopo.md")

    # 4. SALVAR ESTADO
    if session_id and response_text:
        state_manager.add_interaction(session_id, last_message, response_text)

    # 5. RETORNO (Com fontes limpas e cortadas no PIPE)
    raw_sources = [d['meta'] for d in source_docs] if source_docs else []
    clean_sources = _deduplicate_sources(raw_sources)

    return {
        "resposta": response_text,
        "comando_executado": decision_cmd,
        "fontes": clean_sources,
        "session_id": session_id
    }