import os
import logging
from src.shared.llm import call_api_with_messages
from src.orchestrator import classifier
from src.search import rag_core

# --- Helpers de Arquivo ---
def _load_prompt(filename):
    """
    Carrega o prompt procurando na pasta src/prompts relativo a este arquivo.
    """
    try:
        # Pega o caminho absoluto deste arquivo (src/orchestrator/router.py)
        current_file_path = os.path.abspath(__file__)
        
        # Sobe dois níveis para chegar em 'src' (src/orchestrator -> src)
        src_dir = os.path.dirname(os.path.dirname(current_file_path))
        
        # Monta o caminho final: src/prompts/filename
        prompt_path = os.path.join(src_dir, "prompts", filename)
        
        # Normaliza o caminho (arruma barras invertidas no Windows)
        prompt_path = os.path.normpath(prompt_path)

        logging.info(f"Tentando carregar prompt em: {prompt_path}")

        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            logging.error(f"ARQUIVO NÃO EXISTE: {prompt_path}")
            # Tentativa de fallback na raiz (caso mova a pasta depois)
            root_path = os.path.join(os.getcwd(), "prompts", filename)
            if os.path.exists(root_path):
                with open(root_path, "r", encoding="utf-8") as f:
                    return f.read()
            
            return f"Erro: Arquivo '{filename}' não encontrado em {prompt_path}"

    except Exception as e:
        logging.error(f"Erro crítico ao ler arquivo: {e}")
        return "Erro: Falha na leitura do template."

def _format_history(messages):
    """Converte lista de JSON em texto para o LLM entender o contexto"""
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
    Roteador Inteligente (Fast Track)
    """
    # 1. Preparar Histórico
    raw_history = full_body.get("historico", [])
    history_text = _format_history(raw_history)

    # 2. Consultar o "Cérebro" (LLM Router)
    router_template = _load_prompt("router_v2.md")
    
    # Validação de segurança para não gastar token com prompt de erro
    if "Erro:" in router_template:
        logging.error(f"Abortando router. Template inválido: {router_template}")
        return {
            "resposta": "Erro interno: Template de roteamento não encontrado.",
            "comando_executado": "ERROR"
        }

    router_prompt = router_template.replace("{historico}", history_text).replace("{ultima_mensagem}", last_message)
    
    # Chama LLM rápido
    try:
        msgs = [{"role": "system", "content": "Você é um roteador estrito."}, {"role": "user", "content": router_prompt}]
        _, _, decision_cmd = call_api_with_messages(msgs, max_tokens=15, temperature=0.0)
        decision_cmd = decision_cmd.strip().upper() if decision_cmd else "CMD_TECNICA"
    except Exception as e:
        logging.error(f"Erro LLM Router: {e}")
        decision_cmd = "CMD_TECNICA"

    logging.info(f"Router Decision: {decision_cmd} | IP: {client_ip}")

    # 3. Executar a Decisão
    response_text = ""
    source_docs = []

    if decision_cmd == "CMD_TECNICA":
        intent_data = classifier.classify_intent(last_message)
        modulo = intent_data.get("modulo", "fora_escopo")
        
        if modulo == "fora_escopo":
             response_text = _load_prompt("templates/fora_escopo.md")
        else:
             context_docs = rag_core.retrieve_context(last_message)
             
             # Formata contexto
             context_text = "\n\n".join([f"{d['content']} (Fonte: {d['meta']})" for d in context_docs])
             
             # Carrega prompt técnico (ex: technical/avaliacao.md)
             # O classifier retorna 'avaliacao', 'classificacao', etc.
             # Se for necessário ajustar o nome do arquivo, faça aqui.
             # Supondo que seus arquivos sejam: avaliacao.md, classificacao.md
             
             tech_filename = f"technical/{modulo}.md"
             tech_prompt = _load_prompt(tech_filename)
             
             if "Erro:" in tech_prompt:
                 # Fallback se não achar o específico
                 logging.warning(f"Prompt técnico {tech_filename} não achado. Usando base_agent.")
                 tech_prompt = _load_prompt("base_agent.md")

             final_sys_prompt = tech_prompt.replace("{contexto}", context_text).replace("{sub_intencao}", intent_data.get("sub_intencao", "geral")).replace("{emocao}", "neutro")
             
             rag_msgs = [{"role": "system", "content": final_sys_prompt}, {"role": "user", "content": last_message}]
             _, _, response_text = call_api_with_messages(rag_msgs, max_tokens=800, temperature=0.3)
             source_docs = context_docs

    elif decision_cmd == "CMD_ESCOLA":
        response_text = _load_prompt("templates/escola.md")
        
    elif decision_cmd == "CMD_REGIONAL":
        response_text = _load_prompt("templates/regional.md")
        
    elif decision_cmd == "CMD_CHAMADO":
        response_text = _load_prompt("templates/chamado.md")

    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")
        
    else: 
        response_text = _load_prompt("templates/fora_escopo.md")

    # 4. Montar Retorno
    return {
        "resposta": response_text,
        "comando_executado": decision_cmd,
        "fontes": [d['meta'] for d in source_docs] if source_docs else []
    }