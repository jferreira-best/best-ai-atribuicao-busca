import os
import logging
import random
from src.shared.llm import call_api_with_messages
from src.orchestrator import classifier
from src.search import rag_core
from src.shared import state_manager
from src.config.settings import MSG_ENCERRAMENTO_FORCADO

# --- CONFIGURAÇÃO ---
LINK_SISTEMA_CHAMADOS = "https://atendimento.educacao.sp.gov.br"

# --- Helpers ---
def _deduplicate_sources(source_list):
    if not source_list: return []
    seen = set()
    output = []
    for source in source_list:
        clean = source.split('|')[0].strip()
        if clean not in seen:
            output.append(clean)
            seen.add(clean)
    return output

def _load_prompt(filename):
    try:
        current_file_path = os.path.abspath(__file__)
        src_dir = os.path.dirname(os.path.dirname(current_file_path))
        prompt_path = os.path.join(src_dir, "prompts", filename)
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        logging.error(f"Prompt {filename} não encontrado em: {prompt_path}")
        return f"Erro: Prompt {filename} não encontrado."
    except Exception as e:
        logging.error(f"Erro prompt {filename}: {e}")
        return "Erro interno."

def _verificar_trava_exaustao(history):
    if not history: return False
    last = history[-1] 
    if last.get("role") == "assistant":
        if MSG_ENCERRAMENTO_FORCADO.lower() in last.get("content", "").lower():
            return True
    return False

def _verificar_escalonamento(last_user_msg, history):
    """Detecta se usuário recusou ir à escola após sugestão do bot."""
    if not history: return False
    
    # Pega última msg do bot
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = msg.get("content", "").lower()
            break
            
    if not last_bot_msg: return False

    # Bot sugeriu presencial?
    triggers_bot = ["trio gestor", "secretaria da escola", "diretoria de ensino"]
    if not any(t in last_bot_msg for t in triggers_bot):
        return False

    # Usuário negou?
    user_txt = last_user_msg.lower()
    triggers_user = ["não vou", "nao vou", "não quero", "recuso", "abrir chamado", "link"]
    
    if any(t in user_txt for t in triggers_user):
        logging.info("Escalonamento detectado: Usuário quer link.")
        return True
    return False

def _verificar_contexto_continuacao(last_user_msg, history):
    """
    [NOVO] Verifica se o usuário está respondendo a uma pergunta de desambiguação
    (Efetivo vs Contratado).
    """
    if not history: return None

    # 1. Pega última fala do Bot
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = msg.get("content", "").lower()
            break
    
    if not last_bot_msg: return None

    # 2. Verifica se o Bot perguntou sobre categoria (Prompt Classificacao)
    # Frases chave: "efetivo ou contratado", "qual sua categoria"
    if "efetivo" in last_bot_msg and "contratado" in last_bot_msg and "?" in last_bot_msg:
        
        user_txt = last_user_msg.lower()
        # Palavras que indicam uma resposta válida
        keywords = ["efetivo", "titular", "estavel", "contratado", "categoria o", "cat o", "temporario"]
        
        if any(k in user_txt for k in keywords):
            logging.info(f"Contexto detectado: Resposta de categoria ('{last_user_msg}'). Forçando Classificação.")
            return "classificacao"

    return None

# --- Main Router ---
def route_request(last_message: str, body: dict, client_ip: str):
    session_id = body.get("session_id", "sessao_anonima")
    logging.info(f"Router iniciado. Session: {session_id}")

    # 1. HISTÓRICO
    history = state_manager.get_history(session_id, limit=6)

    # 2. CIRCUIT BREAKER
    if _verificar_trava_exaustao(history):
        return {"answer": MSG_ENCERRAMENTO_FORCADO, "fontes": [], "intent": "bloqueio_exaustao"}

    # 3. ESCALONAMENTO (Link Chamado)
    if _verificar_escalonamento(last_message, history):
        decision_cmd = "CMD_CHAMADO"
        decision = {"modulo": "atendimento", "sub_intencao": "abrir_chamado"}
    
    else:
        # 4. CHECAGEM DE CONTEXTO (Resposta Curta do Usuário)
        modulo_contextual = _verificar_contexto_continuacao(last_message, history)
        
        if modulo_contextual:
            # Pula o classificador e força a intenção correta
            decision = {"modulo": modulo_contextual, "sub_intencao": "resposta_usuario_categoria"}
            decision_cmd = "CMD_TECNICA"
            logging.info(f"Override Contextual Ativado: {modulo_contextual}")
        else:
            # 5. CLASSIFICAÇÃO PADRÃO (LLM)
            decision = classifier.classify_intent(last_message)
            logging.info(f"Router Decision inicial: {decision['modulo']}")

            decision_cmd = "CMD_FORA_ESCOPO"
            mod = decision["modulo"]
            
            if mod in ["avaliacao", "classificacao", "alocacao"]:
                decision_cmd = "CMD_TECNICA"
            elif decision["sub_intencao"] == "diretriz_escola":
                decision_cmd = "CMD_ESCOLA"
            elif decision["sub_intencao"] == "diretriz_regional":
                decision_cmd = "CMD_REGIONAL"
            elif decision["sub_intencao"] == "abrir_chamado":
                decision_cmd = "CMD_CHAMADO"
            elif decision["sub_intencao"] == "encerrar_conversa":
                decision_cmd = "CMD_FINALIZACAO"

    logging.info(f"Router Decision final: {decision_cmd}")

    response_text = ""
    source_docs = []

    # 6. EXECUÇÃO
    if decision_cmd == "CMD_TECNICA":
        
        # [NOVO] ENRIQUECIMENTO DE QUERY
        # Se o usuário respondeu só "contratado", o RAG vai falhar se buscar só isso.
        # Vamos ajudar o RAG expandindo a busca.
        query_to_rag = last_message
        if decision.get("sub_intencao") == "resposta_usuario_categoria":
            query_to_rag = f"Regras de classificação e pontuação para docente {last_message}"
            logging.info(f"Query Enriquecida para RAG: '{query_to_rag}'")

        # Busca no RAG
        context_docs = rag_core.retrieve_context(query_to_rag)
        context_str = "\n".join([d['content'] for d in context_docs])
        
        # Seleciona Prompt
        mod = decision["modulo"]
        prompt_file = f"technical/{mod}.md" if mod in ["avaliacao", "classificacao", "alocacao"] else "alocacao.md"
        
        sys_prompt = _load_prompt(prompt_file)
        if "Erro:" not in sys_prompt:
            final_prompt = sys_prompt.replace("{contexto}", context_str)\
                                     .replace("{pergunta}", last_message)\
                                     .replace("{sub_intencao}", decision.get("sub_intencao", "geral"))\
                                     .replace("{emocao}", decision.get("emocao", "neutro"))
            
            rag_msgs = [{"role": "system", "content": final_prompt}, {"role": "user", "content": last_message}]
            _, _, response_text = call_api_with_messages(rag_msgs, max_tokens=800, temperature=0.0)
            
            source_docs = _deduplicate_sources([d['meta'] for d in context_docs])
        else:
            response_text = "Erro interno: Prompt técnico indisponível."

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
        # Roleta de Respostas para Fora de Escopo
        msgs_erro = [
            "Olá! Sou especialista em **Avaliação**, **Classificação** e **Alocação**. Para outros assuntos (boletim, pagamentos, etc), procure a secretaria da escola.",
            "Qual sua dúvida específica sobre **Classificação** ou **Atribuição**? Para outros temas, recomendo o portal da SEDUC.",
            "Ainda estou aprendendo! Consigo ajudar com **PEI**, **Avaliação** e **Classificação**. Se for outro assunto, consulte o gerente da sua escola."
        ]
        response_text = random.choice(msgs_erro)

    # 7. SALVAR
    if session_id and response_text:
        state_manager.add_interaction(session_id, last_message, response_text)

    return {
        "answer": response_text,
        "fontes": source_docs,
        "intent": decision["modulo"],
        "confidence": decision.get("confianca", 1.0)
    }