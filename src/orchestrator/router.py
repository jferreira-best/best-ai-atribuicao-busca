import os
import logging
from src.shared.llm import call_api_with_messages
from src.orchestrator import classifier
from src.search import rag_core
from src.shared import state_manager

# [NOVO] Importa a mensagem de bloqueio configurada no settings
from src.config.settings import MSG_ENCERRAMENTO_FORCADO

# --- CONFIGURAÇÃO ---
LINK_SISTEMA_CHAMADOS = "https://atendimento.educacao.sp.gov.br"

# --- Helpers ---
def _deduplicate_sources(source_list):
    if not source_list:
        return []
    seen = set()
    output = []
    for source in source_list:
        clean_source = source.split('|')[0].strip()
        if clean_source not in seen:
            output.append(clean_source)
            seen.add(clean_source)
    return output

def _load_prompt(filename):
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

# [NOVO] Lógica de verificação de exaustão baseada no histórico
def _verificar_trava_exaustao(history_messages):
    """
    Verifica se a última interação do sistema já foi uma tratativa final.
    Retorna True se deve bloquear o fluxo.
    """
    if not history_messages:
        return False
    
    # Pega a última mensagem (assume ordem cronológica)
    # Procura a última mensagem que seja do 'assistant'
    last_assistant_msg = None
    for msg in reversed(history_messages):
        if msg.get("role") == "assistant":
            last_assistant_msg = msg.get("content", "")
            break
    
    if not last_assistant_msg:
        return False
        
    # Critérios de Bloqueio (O que define que o papo acabou?)
    # 1. Se a última mensagem já foi o Encerramento Forçado (evita loop)
    if MSG_ENCERRAMENTO_FORCADO in last_assistant_msg:
        return True
        
    # 2. Se a última mensagem continha o LINK do sistema (CMD_CHAMADO)
    if LINK_SISTEMA_CHAMADOS in last_assistant_msg:
        return True
        
    # 3. Adicione aqui trechos chave das mensagens de CMD_ESCOLA ou CMD_REGIONAL
    # Exemplo: Se o template escola.md contém a frase "procure o Trio Gestor"
    frases_finais = [
        "procure o Trio Gestor",       # Exemplo do template escola
        "Diretoria de Ensino",         # Exemplo do template regional
        "atendimento encerrado"
    ]
    
    for frase in frases_finais:
        if frase.lower() in last_assistant_msg.lower():
            return True
            
    return False

# --- Função Principal ---
def route_request(last_message: str, full_body: dict, client_ip: str):
    """
    Roteador Inteligente (Fast Track) com Sanitização Robusta
    """
    
    # 1. SANITIZAÇÃO TOTAL
    if last_message:
        last_message = " ".join(last_message.split())

    # 2. GERENCIAMENTO DE ESTADO
    session_id = full_body.get("session_id")
    raw_history = []
    
    if session_id:
        logging.info(f"SessionID: {session_id}. Buscando histórico...")
        raw_history = state_manager.get_history(session_id)
    else:
        raw_history = full_body.get("historico", [])

    # ==========================================================================
    # [NOVO] 2.1 CIRCUIT BREAKER (Trava de Exaustão)
    # Antes de chamar qualquer IA, verifica se já finalizamos na rodada anterior.
    # ==========================================================================
    if _verificar_trava_exaustao(raw_history):
        logging.info(f"Circuit Breaker ativado para SessionID: {session_id}. Enviando mensagem de encerramento.")
        return {
            "resposta": MSG_ENCERRAMENTO_FORCADO,
            "comando_executado": "CMD_BLOQUEIO_EXAUSTAO",
            "fontes": [],
            "session_id": session_id
        }
    # ==========================================================================

    history_text = _format_history(raw_history)

    # 3. Consultar o Router (LLM)
    router_template = _load_prompt("router_v2.md")
    
    if "Erro:" in router_template:
        return {"resposta": "Erro interno: Template router não encontrado.", "comando": "ERROR"}

    router_prompt = router_template.replace("{historico}", history_text).replace("{ultima_mensagem}", last_message)
    
    decision_cmd = "CMD_TECNICA"
    try:
        msgs = [
            {"role": "system", "content": "Você é um roteador estrito."},
            {"role": "user", "content": router_prompt}
        ]
        _, _, llm_decision = call_api_with_messages(
            msgs,
            max_tokens=15,
            temperature=0.0
        )
        if llm_decision:
            decision_cmd = llm_decision.strip().upper()
    except Exception as e:
        logging.error(f"Erro LLM Router: {e}")

    logging.info(f"Router Decision inicial: {decision_cmd} | IP: {client_ip}")

    # 3B. SANITY CHECK COM CLASSIFICADOR
    if decision_cmd == "CMD_FORA_ESCOPO":
        try:
            intent_preview = classifier.classify_intent(last_message)
            modulo_preview = intent_preview.get("modulo", "fora_escopo")
            if modulo_preview in ("avaliacao", "classificacao", "alocacao"):
                logging.info(
                    f"Override decision para CMD_TECNICA com base no classificador. "
                    f"Modulo_preview={modulo_preview}"
                )
                decision_cmd = "CMD_TECNICA"
        except Exception as e:
            logging.error(f"Erro no sanity check do classificador: {e}")

    logging.info(f"Router Decision final: {decision_cmd} | IP: {client_ip}")

    # 4. Executar Decisão
    response_text = ""
    source_docs = []

    if decision_cmd == "CMD_TECNICA":
        intent_data = classifier.classify_intent(last_message)
        modulo = intent_data.get("modulo", "fora_escopo")
        
        if modulo == "fora_escopo":
             response_text = _load_prompt("templates/fora_escopo.md")
        else:
             context_docs = rag_core.retrieve_context(last_message)
             context_text = "\n\n".join([f"{d['content']} (Fonte: {d['meta']})" for d in context_docs])
             
             tech_filename = f"technical/{modulo}.md"
             tech_prompt = _load_prompt(tech_filename)
             
             if "Erro:" in tech_prompt:
                 tech_prompt = _load_prompt("base_agent.md")

             if "Erro:" in tech_prompt:
                 response_text = "Erro interno: Prompt técnico não encontrado."
             else:
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
        response_text = tpl.replace("[Inserir Link do Portal de Chamados Aqui]", LINK_SISTEMA_CHAMADOS)

    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")
        
    else: 
        response_text = _load_prompt("templates/fora_escopo.md")

    # 5. SALVAR ESTADO
    if session_id and response_text:
        # Se quiser refinar no futuro, pode salvar metadata={"cmd": decision_cmd}
        state_manager.add_interaction(session_id, last_message, response_text)

    # 6. RETORNO
    raw_sources = [d['meta'] for d in source_docs] if source_docs else []
    clean_sources = _deduplicate_sources(raw_sources)

    return {
        "resposta": response_text,
        "comando_executado": decision_cmd,
        "fontes": clean_sources,
        "session_id": session_id
    }