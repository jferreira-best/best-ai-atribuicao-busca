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
        if "respeitamos a sua manifestacao" in content:
            return True
        if _normalize_text(MSG_ENCERRAMENTO_FORCADO) in content:
            return True
    return False

def _verificar_critica_severa(text, classification=None):
    text_norm = _normalize_text(text)
    termos_toxicos = [
        "porcaria", "lixo", "bosta", "merda", "inutil", "nao presta", 
        "desgraca", "idiota", "burro", "imbecil", "ridiculo", 
        "vergonha", "palhacada", "odiei", "horrivel", "pessimo",
        "vai se fuder", "vai a merda", "vai tomar no cu", "filha da puta",
        "sistema ruim", "nada funciona"
    ]
    if any(t in text_norm for t in termos_toxicos):
        return True
    if classification:
        sub = classification.get("sub_intencao")
        emo = classification.get("emocao")
        if sub == "reclamacao_geral" and emo == "raiva":
            return True
    return False

def _identificar_proximo_passo(last_user_msg, history):
    if not history: return None
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = _normalize_text(msg.get("content", ""))
            break
    if not last_bot_msg: return None
    user_txt = _normalize_text(last_user_msg)
    
    termos_instrucao = ["trio gestor", "escola", "regional", "ure", "chamado", "diretor"]
    bot_deu_instrucao = any(termo in last_bot_msg for termo in termos_instrucao)

    triggers_desistencia = [
        "ninguem resolve", "nao vou em lugar nenhum", "nao vou procurar mais ninguem",
        "vou desistir", "cansei dessa merda", "ninguem ajuda", "tudo inutil",
        "nao vou em escola nenhuma"
    ]
    if any(t in user_txt for t in triggers_desistencia):
        return "CMD_CHAMADO"

    triggers_recusa = [
        "ja fui", "ja falei", "ja fiz", "ja procurei", "nao resolveu", 
        "nao adiantou", "nao adianta", "nao concordo", "esta errado", 
        "discordo", "mentira", "incorreto", 
        "nao vou", "nao irei", "nao quero", "me recuso", "sem chance", "jamais"
    ]
    
    is_recusa = False
    for t in triggers_recusa:
        if t in user_txt:
            if t == "nao": 
                 if bot_deu_instrucao: is_recusa = True
            else:
                is_recusa = True
            if is_recusa: break
    
    if is_recusa:
        if "atendimento.educacao.sp.gov.br" in last_bot_msg or "chamado oficial" in last_bot_msg:
            return "CMD_ENCERRAMENTO_TOTAL"
        if "contato com a ure" in last_bot_msg or "unidade regional" in last_bot_msg:
            return "CMD_CHAMADO"
        if "voce vai procurar a escola" in last_bot_msg or "ja realizou esse contato" in last_bot_msg:
            return "CMD_REGIONAL"
        return "CMD_ESCOLA"

    triggers_inercia = [
        "ainda nao", "nao procurei", "nao fui", "ainda nao fui", 
        "nao tive tempo", "vou ver", "vou ver isso"
    ]
    if any(t in user_txt for t in triggers_inercia):
        if "contato com a ure" in last_bot_msg:
            return "CMD_REGIONAL"
        if "voce vai procurar a escola" in last_bot_msg:
            return "CMD_ESCOLA"
        
    triggers_acao = [
        "irei procurar", "vou procurar", "vou la", "vou ir", 
        "farei isso", "fazerei isso", "vou fazer", 
        "vou entrar em contato", "vou ligar", "vou na escola"
    ]
    if any(t in user_txt for t in triggers_acao):
        return "CMD_FINALIZACAO"

    triggers_simples = [
        "ok", "ta bom", "tá bom", "beleza", "combinado", "entendi",
        "pode deixar", "obrigado", "valeu", "certo", "show", "perfeito", 
        "sim", "uhum", "pode ser", "com certeza"
    ]
    if any(t in user_txt for t in triggers_simples):
        if bot_deu_instrucao:
            return "CMD_FINALIZACAO"

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

def _resgatar_intencao_tecnica(text):
    """
    Se o classificador falhar (disser 'fora_escopo'), esta função força
    o módulo correto se encontrar palavras-chave técnicas óbvias.
    """
    norm = _normalize_text(text)
    
    # 1. Avaliação (QAE/Farol - Prioridade Máxima por ser muito específico)
    # Não alteramos nada aqui, continua verificando primeiro.
    if "qae" in norm or "farol" in norm or "indiciadores" in norm or "devolutiva" in norm:
        return "avaliacao"

    # 2. Classificação / Pontuação (MUDANÇA: Subiu de prioridade)
    # Agora verificamos isso ANTES de Alocação. Adicionamos "títulos", "diploma", etc.
    # Assim, "pontuação da atribuição" cai aqui, e não em Alocação.
    termos_classificacao = [
        "vunesp", "pontuacao", "pontos", "classificacao", "remanescente", 
        "diploma", "certificado", "mestrado", "doutorado", "titulos"
    ]
    if any(t in norm for t in termos_classificacao):
        return "classificacao"
    
    # 3. Alocação / PEI / Legislação (Ficou por último)
    # Se não for pontuação nem avaliação, mas tiver termos de atribuição, cai aqui.
    termos_alocacao = [
        "pei", "programa ensino integral", "atribuicao", "alocacao", 
        "jornada", "resolucao", "portaria", "designacao", "artigo 22"
    ]
    
    if any(t in norm for t in termos_alocacao):
        return "alocacao"
        
    return None

# --- Main Router ---
def route_request(last_message: str, body: dict, client_ip: str):
    session_id = body.get("session_id", "sessao_anonima")
    history = state_manager.get_history(session_id, limit=6)

    # 1. Trava de Segurança
    if _verificar_trava_exaustao(history):
        return {"resposta": MSG_ENCERRAMENTO_FORCADO, "fontes": [], "intent": "bloqueio_exaustao"}

    # 2. Filtro de Crítica Severa
    if _verificar_critica_severa(last_message):
        decision_cmd = "CMD_CRITICA_GRAVE"
        decision = {"modulo": "fora_escopo", "sub_intencao": "ofensa_critica", "emocao": "raiva"}
        logging.info("!!! CRITICA SEVERA DETECTADA !!!")
    
    else:
        # 3. Escalonamento
        next_step_cmd = _identificar_proximo_passo(last_message, history)
        
        if next_step_cmd:
            decision_cmd = next_step_cmd
            decision = {"modulo": "atendimento", "sub_intencao": "escalonamento"}
        else:
            # 4. Fluxo Inicial
            modulo_contextual = _verificar_contexto_continuacao(last_message, history)
            if modulo_contextual:
                decision = {"modulo": modulo_contextual, "sub_intencao": "resposta_usuario_categoria"}
                decision_cmd = "CMD_TECNICA"
            else:
                decision = classifier.classify_intent(last_message)
                
                # --- AQUI ENTRA A CORREÇÃO: REDE DE SEGURANÇA ---
                # Se o LLM disse que é Fora de Escopo, mas tem palavra técnica óbvia, nós corrigimos.
                if decision["modulo"] == "fora_escopo":
                    resgate = _resgatar_intencao_tecnica(last_message)
                    if resgate:
                        logging.info(f"RESGATE DE INTENÇÃO: Forçado de fora_escopo para {resgate}")
                        decision["modulo"] = resgate
                        decision["sub_intencao"] = "resgate_keyword"
                        decision_cmd = "CMD_TECNICA"
                    else:
                        # Se não resgatou, mantém a lógica original
                        if _verificar_critica_severa(last_message, classification=decision):
                            decision_cmd = "CMD_CRITICA_GRAVE"
                        else:
                            decision_cmd = "CMD_FORA_ESCOPO"
                else:
                    # Se já veio classificado como técnico, segue o baile
                    mod = decision["modulo"]
                    sub = decision.get("sub_intencao")
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
                    else:
                        decision_cmd = "CMD_FORA_ESCOPO"

    response_text = ""
    source_docs = []

    # --- EXECUÇÃO DOS COMANDOS ---
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

        instrucao_rodape = (
            "\n\n### INSTRUÇÃO OBRIGATÓRIA DE FINALIZAÇÃO:\n"
            "Finalize sua resposta explicando que esta é a regra técnica do sistema.\n"
            "Adicione EXATAMENTE esta frase no final: 'Caso seus dados estejam divergentes ou você discorde do cálculo, "
            "o procedimento correto é procurar o **Trio Gestor da sua escola** para conferência.'"
        )

        final_prompt = sys_prompt + instrucao_rodape
        final_prompt = final_prompt.replace("{contexto}", context_str)\
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
        response_text = (
            "Entendo que você já conversou com o Trio Gestor da sua escola.\n\n"
            "Nesse caso, o próximo passo da escalação é procurar a **Unidade Regional de Ensino (URE)** responsável pela sua unidade. "
            "A equipe da URE possui acesso a níveis superiores do sistema e pode analisar situações que a escola não conseguiu resolver.\n\n"
            "Você vai entrar em contato com a URE ou já fez isso?"
        )

    elif decision_cmd == "CMD_CHAMADO":
        response_text = (
            "Compreendo. Como você já esgotou as instâncias de atendimento presencial (Escola e Regional), a orientação é formalizar sua solicitação via sistema.\n\n"
            "Por favor, **abra um chamado oficial** no portal de atendimento:\n"
            f"{LINK_SISTEMA_CHAMADOS}\n\n"
            "Ao abrir o chamado, relate que já passou pela escola e pela regional sem sucesso. Posso ajudar com mais alguma coisa?"
        )

    elif decision_cmd == "CMD_CRITICA_GRAVE":
        response_text = (
            "Lamento que sua experiência não tenha sido satisfatória e entendo sua frustração.\n\n"
            "Como agente virtual, tenho limitações, mas sua manifestação é importante. "
            "Para que sua crítica seja analisada formalmente e resolvida pela equipe responsável, peço que registre um **chamado oficial** diretamente no portal:\n\n"
            f"🔗 {LINK_SISTEMA_CHAMADOS}\n\n"
            "Lá, uma equipe humana especializada poderá tratar seu caso com a atenção necessária."
        )

    elif decision_cmd == "CMD_ENCERRAMENTO_TOTAL":
        response_text = "Respeitamos a sua manifestação! Entretanto, no campo de um agente digital as orientações foram esgotadas. A partir deste momento o suporte humano é o indicado para seguir com o diálogo."

    elif decision_cmd == "CMD_FINALIZACAO":
        response_text = _load_prompt("templates/finalizacao.md")
        if "Erro" in response_text: 
            response_text = "Fico feliz em ter ajudado! Se precisar de mais alguma informação, estou à disposição."

    else:
        # Fallback genérico
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
                "Sou um assistente focado em regras de **Avaliação de Desempenho**, **Classificação** e **Alocação de Aulas**.",
                "Consigo ajudar com **Avaliação de Desempenho**, **Classificação** e **Alocação de Aulas**. Assuntos administrativos e aleatórios fogem da minha alçada."
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