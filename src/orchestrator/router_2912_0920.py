import os
import logging
import random
import unicodedata
from src.shared.llm import call_api_with_messages
from src.orchestrator import classifier
from src.search import rag_core
from src.shared import state_manager
from src.config.settings import MSG_ENCERRAMENTO_FORCADO

# --- CONFIGURAÇÃO ---
LINK_SISTEMA_CHAMADOS = "https://atendimento.educacao.sp.gov.br"

# --- Helpers ---
def _normalize_text(text):
    """Remove acentos e converte para minúsculo"""
    if not text: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', text) 
                   if unicodedata.category(c) != 'Mn').lower()

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
        logging.error(f"Prompt {filename} não encontrado.")
        return f"Erro: Prompt {filename} não encontrado."
    except Exception as e:
        logging.error(f"Erro prompt {filename}: {e}")
        return "Erro interno."

def _verificar_trava_exaustao(history):
    if not history: return False
    last = history[-1] 
    if last.get("role") == "assistant":
        content = _normalize_text(last.get("content", ""))
        # Verifica se já encerrou (normalizado)
        if "respeitamos a sua manifestacao" in content:
            return True
        if _normalize_text(MSG_ENCERRAMENTO_FORCADO) in content:
            return True
    return False

def _identificar_proximo_passo(last_user_msg, history):
    """
    LÓGICA DA ESCADA: Identifica o degrau atual baseado no que o BOT falou por último.
    """
    if not history: return None

    # 1. Recupera a última fala do Bot (Normalizada)
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = _normalize_text(msg.get("content", ""))
            break
    
    if not last_bot_msg: return None

    # 2. Verifica se o usuário está recusando (Normalizado)
    user_txt = _normalize_text(last_user_msg)
    
    # Lista limpa (sem acentos) porque normalizamos a entrada
    triggers_recusa = [
        "ja fui", "ja falei", "ja fiz",
        "nao resolveu", "nao adiantou", "nao adianta",
        "nao concordo", "esta errado", "discordo",
        "nao quero"
    ]
    
    is_recusa = any(t in user_txt for t in triggers_recusa)
    
    if not is_recusa: return None

    # 3. A Lógica da Escada (Hierarquia)
    
    # FIM DA LINHA (Degrau 4 -> 5)
    if "atendimento.educacao.sp.gov.br" in last_bot_msg or "chamado oficial" in last_bot_msg:
        return "CMD_ENCERRAMENTO_TOTAL"

    # SUBIDA (Degrau 3 -> 4)
    if "regional" in last_bot_msg or "ure" in last_bot_msg or "supervisor" in last_bot_msg:
        return "CMD_CHAMADO"

    # SUBIDA (Degrau 2 -> 3)
    if "trio gestor" in last_bot_msg or "escola" in last_bot_msg or "diretor" in last_bot_msg:
        return "CMD_REGIONAL"

    return None

def _verificar_contexto_continuacao(last_user_msg, history):
    if not history: return None
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = _normalize_text(msg.get("content", ""))
            break
    if not last_bot_msg: return None

    if "efetivo" in last_bot_msg and "contratado" in last_bot_msg:
        user_txt = _normalize_text(last_user_msg)
        keywords = ["efetivo", "titular", "contratado", "categoria o", "cat o", "temporario"]
        if any(k in user_txt for k in keywords):
            return "classificacao"
    return None

# --- Main Router ---
def route_request(last_message: str, body: dict, client_ip: str):
    session_id = body.get("session_id", "sessao_anonima")
    history = state_manager.get_history(session_id, limit=6)

    # 1. Trava de Segurança
    if _verificar_trava_exaustao(history):
        return {"resposta": MSG_ENCERRAMENTO_FORCADO, "fontes": [], "intent": "bloqueio_exaustao"}

    # 2. Escalonamento Hierárquico
    next_step_cmd = _identificar_proximo_passo(last_message, history)
    
    if next_step_cmd:
        decision_cmd = next_step_cmd
        decision = {"modulo": "atendimento", "sub_intencao": "escalonamento"}
        logging.info(f"Escalonamento ativado: {decision_cmd}")
    else:
        # 3. Fluxo Inicial
        modulo_contextual = _verificar_contexto_continuacao(last_message, history)
        if modulo_contextual:
            decision = {"modulo": modulo_contextual, "sub_intencao": "resposta_usuario_categoria"}
            decision_cmd = "CMD_TECNICA"
        else:
            decision = classifier.classify_intent(last_message)
            logging.info(f"Classificacao: {decision}")
            
            decision_cmd = "CMD_FORA_ESCOPO"
            mod = decision["modulo"]
            sub = decision.get("sub_intencao")

            # Tratamento de discórdia inicial (Início da Escada)
            if mod in ["avaliacao", "classificacao", "alocacao"]:
                if sub in ["questionar_calculo", "reportar_erro_dados"]:
                    decision_cmd = "CMD_ESCOLA"
                else:
                    decision_cmd = "CMD_TECNICA"
            
            elif sub == "diretriz_escola":
                decision_cmd = "CMD_ESCOLA"
            elif sub == "diretriz_regional":
                decision_cmd = "CMD_REGIONAL"
            elif sub == "abrir_chamado":
                decision_cmd = "CMD_CHAMADO"
            elif sub == "encerrar_conversa":
                decision_cmd = "CMD_FINALIZACAO"

    response_text = ""
    source_docs = []

    # --- EXECUÇÃO DOS COMANDOS ---
    
    if decision_cmd == "CMD_TECNICA":
        # Nota: Mantemos last_message original pro RAG (busca pode precisar de acentos),
        # mas o classificador já garantiu o tema.
        query_to_rag = last_message
        sub_intent = decision.get("sub_intencao", "geral")
        if sub_intent == "resposta_usuario_categoria":
            query_to_rag = f"Regras de classificação e pontuação para docente {last_message}"
        
        context_docs = rag_core.retrieve_context(query_to_rag)
        context_str = "\n".join([d['content'] for d in context_docs])
        
        mod = decision["modulo"]
        prompt_file = f"technical/{mod}.md" if mod in ["avaliacao", "classificacao", "alocacao"] else "alocacao.md"
        sys_prompt = _load_prompt(prompt_file)

        final_prompt = sys_prompt.replace("{contexto}", context_str)\
                                    .replace("{pergunta}", last_message)\
                                    .replace("{sub_intencao}", sub_intent)\
                                    .replace("{emocao}", decision.get("emocao", "neutro"))
        
        rag_msgs = [{"role": "system", "content": final_prompt}, {"role": "user", "content": last_message}]
        _, _, response_text = call_api_with_messages(rag_msgs, max_tokens=800, temperature=0.0)
        source_docs = _deduplicate_sources([d['meta'] for d in context_docs])

    elif decision_cmd == "CMD_ESCOLA":
        response_text = (
            "Entendo sua preocupação e percebo que você ainda tem dúvidas ou discorda da explicação técnica apresentada.\n\n"
            "Como sua questão envolve análise de dados específicos do seu caso, o procedimento correto é procurar o "
            "**Trio Gestor da sua Unidade Escolar** (Diretor, Vice-Diretor ou Coordenador). Eles têm acesso aos seus dados no sistema e podem verificar particularidades.\n\n"
            "Você vai procurar a escola ou já realizou esse contato?"
        )

    elif decision_cmd == "CMD_REGIONAL":
        tpl = _load_prompt("templates/regional.md")
        response_text = "Entendo que você já conversou com o Trio Gestor da sua escola.\n\nNesse caso, o próximo passo da escalação é procurar a **Unidade Regional de Ensino (URE)** responsável pela sua unidade. A equipe da URE possui acesso a níveis superiores do sistema e pode analisar situações que a escola não conseguiu resolver.\n\nVocê vai entrar em contato com a URE ou já fez isso?"

    elif decision_cmd == "CMD_CHAMADO":
        tpl = _load_prompt("templates/chamado.md")
        response_text = (
            "Compreendo. Como você já esgotou as instâncias de atendimento presencial (Escola e Regional), a orientação é formalizar sua solicitação via sistema.\n\n"
            "Por favor, **abra um chamado oficial** no portal de atendimento:\n"
            f"{LINK_SISTEMA_CHAMADOS}\n\n"
            "Ao abrir o chamado, relate que já passou pela escola e pela regional sem sucesso. Posso ajudar com mais alguma coisa?"
        )

    elif decision_cmd == "CMD_ENCERRAMENTO_TOTAL":
        response_text = "Respeitamos a sua manifestação! Entretanto, no campo de um agente digital as orientações foram esgotadas. A partir deste momento o suporte humano é o indicado para seguir com o diálogo."

    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")

    else:
        sub = decision.get("sub_intencao")
        emo = decision.get("emocao")
        
        if sub == "reclamacao_geral" or emo in ["frustracao", "raiva", "insatisfeito"]:
            response_text = (
               "Sinto muito pela sua insatisfação. Meu objetivo é apoiar com regras técnicas. "
               "Se houver uma discordância de valores ou dados, recomendo iniciar o contato pelo **Trio Gestor da sua escola**."
            )
        elif sub == "duvida_aluno":
             msgs_aluno = [
                 "Notei que sua dúvida parece ser sobre vida escolar. Sou especializado apenas em RH Docente. Para dados de alunos, use a SED.",
                 "Como meu foco são as regras de atribuição de aulas, não tenho acesso a dados de alunos."
             ]
             response_text = random.choice(msgs_aluno)
        else:
            msgs = [
                "Sou um assistente focado em regras de **Avaliação** e **Atribuição**.",
                "Consigo ajudar com **Classificação** e **Alocação**. Assuntos administrativos fogem da minha alçada."
            ]
            response_text = random.choice(msgs)

    if session_id and response_text:
        state_manager.add_interaction(session_id, last_message, response_text)

    return {
        "resposta": response_text,
        "fontes": source_docs,
        "intent": decision["modulo"],
        "confidence": decision.get("confianca", 1.0)
    }