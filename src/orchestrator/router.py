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
        logging.error(f"Prompt {filename} não encontrado.")
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
    if not history: return False
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = msg.get("content", "").lower()
            break
    if not last_bot_msg: return False

    triggers_bot = ["trio gestor", "secretaria da escola", "diretoria de ensino"]
    if not any(t in last_bot_msg for t in triggers_bot): return False

    user_txt = last_user_msg.lower()
    triggers_user = ["não vou", "nao vou", "não quero", "recuso", "abrir chamado", "link", "adianta"]
    if any(t in user_txt for t in triggers_user):
        return True
    return False

def _verificar_contexto_continuacao(last_user_msg, history):
    if not history: return None
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = msg.get("content", "").lower()
            break
    if not last_bot_msg: return None

    if "efetivo" in last_bot_msg and "contratado" in last_bot_msg:
        user_txt = last_user_msg.lower()
        keywords = ["efetivo", "titular", "contratado", "categoria o", "cat o", "temporario"]
        if any(k in user_txt for k in keywords):
            return "classificacao"
        
    if "link" in last_bot_msg or "chamado" in last_bot_msg:
        user_txt = last_user_msg.lower()
        if user_txt in ["sim", "quero", "por favor", "manda", "ok"]:
             logging.info("Contexto: Usuário aceitou oferta de chamado.")
             return "atendimento" # Vai forçar cair no CMD_CHAMADO se mapeado
            
    return None

# --- Main Router ---
def route_request(last_message: str, body: dict, client_ip: str):
    session_id = body.get("session_id", "sessao_anonima")
    history = state_manager.get_history(session_id, limit=6)

    # 1. Trava
    if _verificar_trava_exaustao(history):
        return {"answer": MSG_ENCERRAMENTO_FORCADO, "fontes": [], "intent": "bloqueio_exaustao"}

    # 2. Escalonamento
    if _verificar_escalonamento(last_message, history):
        decision_cmd = "CMD_CHAMADO"
        decision = {"modulo": "atendimento", "sub_intencao": "abrir_chamado"}
    else:
        # 3. Classificação / Contexto
        modulo_contextual = _verificar_contexto_continuacao(last_message, history)
        if modulo_contextual:
            decision = {"modulo": modulo_contextual, "sub_intencao": "resposta_usuario_categoria"}
            decision_cmd = "CMD_TECNICA"
        else:
            decision = classifier.classify_intent(last_message)
            logging.info(f"Classificacao: {decision}")
            
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

    response_text = ""
    source_docs = []

    if decision_cmd == "CMD_TECNICA":
        query_to_rag = last_message
        sub_intent = decision.get("sub_intencao", "geral")

        if sub_intent == "resposta_usuario_categoria":
            query_to_rag = f"Regras de classificação e pontuação para docente {last_message}"
        
        context_docs = rag_core.retrieve_context(query_to_rag)
        context_str = "\n".join([d['content'] for d in context_docs])
        
        mod = decision["modulo"]
        prompt_file = f"technical/{mod}.md" if mod in ["avaliacao", "classificacao", "alocacao"] else "alocacao.md"
        sys_prompt = _load_prompt(prompt_file)

        instrucao_extra = ""
        if sub_intent in ["reportar_erro_dados", "questionar_calculo"]:
            instrucao_extra = (
                "\n\n### DIRETRIZ DE ATENDIMENTO (DISCORDÂNCIA):\n"
                "Oriente a hierarquia: 1. Trio Gestor (Escola) -> 2. Diretoria de Ensino."
            )

        if "Erro:" not in sys_prompt:
            final_prompt = sys_prompt + instrucao_extra
            final_prompt = final_prompt.replace("{contexto}", context_str)\
                                       .replace("{pergunta}", last_message)\
                                       .replace("{sub_intencao}", sub_intent)\
                                       .replace("{emocao}", decision.get("emocao", "neutro"))
            
            rag_msgs = [{"role": "system", "content": final_prompt}, {"role": "user", "content": last_message}]
            _, _, response_text = call_api_with_messages(rag_msgs, max_tokens=800, temperature=0.0)
            source_docs = _deduplicate_sources([d['meta'] for d in context_docs])
        else:
            response_text = "Erro interno."

    elif decision_cmd == "CMD_ESCOLA":
        response_text = _load_prompt("templates/escola.md")
    elif decision_cmd == "CMD_REGIONAL":
        response_text = _load_prompt("templates/regional.md")
    elif decision_cmd == "CMD_CHAMADO":
        tpl = _load_prompt("templates/chamado.md")
        prefixo = ""
        if decision.get("modulo") == "atendimento": prefixo = "Entendo. Como a instância escolar não resolveu, segue o link:\n\n"
        response_text = prefixo + tpl.replace("[Inserir Link do Portal de Chamados Aqui]", LINK_SISTEMA_CHAMADOS)
    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")
    else:
        # --- LÓGICA DE TRATAMENTO DE RAIVA / RECLAMAÇÃO ---
        sub = decision.get("sub_intencao")
        emo = decision.get("emocao")
        
        if sub == "reclamacao_geral" or emo in ["frustracao", "raiva", "insatisfeito"]:
            # Resposta Empática para usuário bravo
            response_text = (
                "Lamento que sua experiência não esteja sendo satisfatória. "
                "Como sou um assistente virtual em fase de treinamento, meu escopo técnico é limitado.\n\n"
                "Para registrar sua insatisfação formalmente e garantir que ela chegue aos responsáveis, "
                f"recomendo abrir um chamado na Ouvidoria através deste link: {LINK_SISTEMA_CHAMADOS}"
            )
        elif sub == "duvida_aluno":
             response_text = "Olá! Sou exclusivo para Docentes. Para dados de alunos (notas, boletim), acesse a Secretaria Escolar Digital (SED)."
        else:
            # Roleta Padrão
            msgs = [
                "Sou um assistente focado em regras de **Avaliação** e **Atribuição** para professores.",
                "Ainda estou aprendendo! Consigo ajudar com **Classificação** e **Alocação**.",
                "Para assuntos administrativos (pagamento, etc), procure a secretaria da escola."
            ]
        # --- LÓGICA DE TRATAMENTO DE RAIVA / RECLAMAÇÃO ---
        sub = decision.get("sub_intencao")
        emo = decision.get("emocao")
        
        if sub == "reclamacao_geral" or emo in ["frustracao", "raiva", "insatisfeito"]:
            # Resposta Empática e Assertiva (Não pede desculpa excessiva, mas resolve)
            response_text = (
                "Entendo perfeitamente sua insatisfação. Como assistente virtual focado em regras técnicas, "
                "minha atuação é limitada nesses casos.\n\n"
                "Para que sua reclamação seja tratada com a devida prioridade, o caminho oficial e auditável "
                f"é através da Ouvidoria neste link: {LINK_SISTEMA_CHAMADOS}"
            )
        elif sub == "duvida_aluno":
             # Variação para não parecer mensagem gravada
             msgs_aluno = [
                 "Notei que sua dúvida parece ser sobre vida escolar (notas, boletim). Sou especializado apenas em RH Docente. Para esses dados, a SED é o caminho correto.",
                 "Como meu foco são as regras de atribuição de aulas, não tenho acesso ao banco de dados de alunos. Recomendo verificar na Secretaria Escolar Digital."
             ]
             response_text = random.choice(msgs_aluno)
        else:
            # Roleta Padrão (Humanizada)
            msgs = [
                "No momento, sou treinado especificamente para responder sobre **Avaliação**, **Classificação** e **Atribuição**. Assuntos administrativos fogem da minha alçada técnica.",
                "Ainda estou em aprendizado! Consigo te dar suporte técnico sobre **PEI** e **Alocação**. Para outros temas, a secretaria da escola é a melhor referência.",
                "Minha base de conhecimento cobre regras de RH (Docentes). Se sua dúvida for administrativa (pagamento, holerite), sugiro contatar o gerente da sua unidade."
            ]
            response_text = random.choice(msgs)

    if session_id and response_text:
        state_manager.add_interaction(session_id, last_message, response_text)

    return {
        "answer": response_text,
        "fontes": source_docs,
        "intent": decision["modulo"],
        "confidence": decision.get("confianca", 1.0)
    }