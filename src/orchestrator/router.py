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
    """
    AJUSTADO: Separa quem JÁ FOI (Escalação) de quem NÃO QUER IR (Recusa).
    """
    if not history: return None
    
    # 1. Recupera mensagem anterior do bot
    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            raw_content = msg.get("content", "")
            last_bot_msg = _normalize_text(raw_content).replace("*", "").replace("\n", " ")
            break
            
    if not last_bot_msg: last_bot_msg = "" 

    user_txt = _normalize_text(last_user_msg)
    
    # 2. Identificação de Contexto
    ctx_escola = any(t in last_bot_msg for t in [
        "trio gestor", "procurar a escola", "unidade escolar", 
        "diretor", "vice-diretor", "coordenador", "gestao da escola"
    ])
    
    ctx_regional = any(t in last_bot_msg for t in [
        "contato com a ure", "unidade regional", "dirigente regional",
        "supervisão de ensino", "diretoria de ensino"
    ])
    
    ctx_chamado = any(t in last_bot_msg for t in [
        "atendimento.educacao.sp.gov.br", "chamado oficial", "portal de atendimento"
    ])

    # 3. Triggers de Desistência
    triggers_desistencia = [
        "ninguem resolve", "nao vou em lugar nenhum", "nao vou procurar mais ninguem",
        "vou desistir", "cansei dessa merda", "ninguem ajuda", "tudo inutil",
        "nao vou em escola nenhuma", "deixa pra la", "esquece"
    ]
    if any(t in user_txt for t in triggers_desistencia):
        return "CMD_ENCERRAMENTO_TOTAL" if ctx_chamado else "CMD_CHAMADO"

    # 4. SUPER LISTA DE ESCALAÇÃO (Aumentada e Validada)
    triggers_escalacao = [
        # --- GRUPO A: Ação Já Realizada (Passado) ---
        "ja fui", "ja falei", "ja fiz", "ja procurei", "ja liguei", 
        "ja conversei", "ja estive", "ja realizei", "ja tentei",
        "ja entrei em contato", "ja mandei", "ja enviei", "ja questionei",
        "ja perguntei", "ja informei", "ja passei", "ja solicitei",
        "ja reclamei", "ja reportei", "ja vi", "ja consultei",
        "ja contatei", "ja busquei", "ja notifiquei", "ja protocolei",
        "ja abri", "ja registrei", "ja comuniquei", "ja avisei",
        "ja cobrei", "ja fui la", "ja estive la", "ja compareci",
        "ja", "fui la", "estive la", "falei com eles", "conversei com eles",
        
        # --- GRUPO B: Ineficácia / Problema Persiste (Onde a escola falhou) ---
        "nao resolveu", "nao adiantou", "nao adianta", "nao solucionou",
        "nao funcionou", "nao deu certo", "nao obtive", "nao mudou",
        "sem sucesso", "sem exito", "sem resposta", "sem solucao",
        "sem retorno", "sem previsao", "nada feito", "nada resolvido",
        "continua igual", "mesmo problema", "nenhuma solucao", "em vao",
        "foi inutil", "perda de tempo", "eles nao resolvem", "eles nao sabem",
        "ninguem sabe", "ninguem resolve", "nao foi resolvido",
        "eles nao irao mudar", "eles nao mudam", "eles nao ajudam",
        "eles ignoram", "eles nao explicam", "eles nao respondem",
        "nao teve jeito", "ficou na mesma", "travado", "parado",
        "nao sabem explicar", "nao sabem orientar", "nao me ajudaram",
        
        # --- GRUPO C: Perguntas de Próximo Passo (Futuro / Desorientação) ---
        "e agora", "e depois", "depois disso", "apos isso", 
        "o que faco", "o que fazer", "fazer o que", "faco o que",
        "qual o proximo", "qual o passo", "proxima etapa", "proximo passo",
        "para onde vou", "aonde vou", "onde ir", "onde devo ir",
        "quem procuro", "procuro quem", "quem resolve", "com quem falo",
        "falo com quem", "pra quem ligo", "qual telefone", "tem contato",
        "mais alguem", "outra opcao", "outra alternativa", "outro caminho",
        "como proceder", "como faco", "como agir", "como resolver",
        "entao o que", "se nao der certo", "e ai", "qual a saida",
        "qual a solucao", "quem pode ajudar", "quem pode resolver",
        "me orienta", "me ajuda", "o que resta"
    ]

    # 5. SUPER LISTA DE RECUSA (Expandida - Recusa, Discordância e Inação)
    triggers_recusa = [
        # --- GRUPO A: Negação de Ir (Recusa) ---
        "nao vou", "nao irei", "nao quero", "me recuso", "sem chance", 
        "jamais", "nunca", "de jeito nenhum", "nem pensar", 
        "recuso", "nao pretendo", "nao estou afim", "nao vou ir",
        "nao vou procurar", "nao vou falar", "nao vou ligar",
        "impossivel ir", "inviavel", "nao rola", "nao da para ir",
        "nao posso ir", "nao tenho como ir", "nao quero ir",
        
        # --- GRUPO B: Discordância dos Dados/Regra (O Usuário acha que está certo) ---
        "nao concordo", "esta errado", "discordo", "mentira", "incorreto",
        "errada", "equivocado", "falso", "absurdo", "injusto", "falha",
        "bug", "erro do sistema", "calculo errado", "contagem errada",
        "divergencia", "incoerente", "nao aceito", "nao procede",
        "nao e verdade", "dados errados", "informacao errada",
        "isso nao existe", "voce esta errado", "nao bate",
        
        # --- GRUPO C: Inação / Ainda não foi ---
        "nao fui", "nao procurei", "ainda nao", "nao liguei",
        "nao conversei", "nao tentei", "nao estive", "nao falei",
        "nao fiz", "esqueci", "nao tive tempo", "nao deu tempo",
        
        # --- GRUPO D: Conflito Pessoal (Medo/Raiva da Escola) ---
        "eles nao gostam de mim", "diretor nao gosta", "perseguicao",
        "tenho problemas la", "sou perseguido", "briguei la",
        "clima ruim", "mau atendimento", "nao me atendem bem"
    ]
    
    # LÓGICA DE DECISÃO CORRIGIDA
    
    # A. Prioridade: Se já fez, escala
    if any(t in user_txt for t in triggers_escalacao):
        if ctx_chamado: return "CMD_ENCERRAMENTO_TOTAL"
        if ctx_regional: return "CMD_CHAMADO"
        return "CMD_REGIONAL" # Padrão: Se já foi na escola, vai pra regional

    # B. Se recusa ou não foi, insiste na escola (Obedecendo o fluxo)
    if any(t in user_txt for t in triggers_recusa):
        return "CMD_INSISTENCIA_ESCOLA"

    # 6. Aceite / Encerramento Positivo
    triggers_aceite = [
        "irei procurar", "vou procurar", "vou la", "vou ir", 
        "farei isso", "fazerei isso", "vou fazer", 
        "vou entrar em contato", "vou ligar", "vou na escola",
        "ok", "ta bom", "tá bom", "beleza", "combinado", "entendi",
        "pode deixar", "obrigado", "valeu", "certo", "show", "perfeito", 
        "sim", "uhum", "pode ser", "com certeza"
    ]
    
    if any(t in user_txt for t in triggers_aceite):
        return "CMD_FINALIZACAO"

    return None

def _verificar_contexto_continuacao(last_user_msg, history):
    if not history: 
        return None

    last_bot_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_bot_msg = _normalize_text(msg.get("content", ""))
            break

    if not last_bot_msg:
        return None

    # Só entra aqui se o último contexto realmente era sobre "efetivo x contratado"
    if "efetivo" in last_bot_msg and "contratado" in last_bot_msg:
        user_txt = _normalize_text(last_user_msg)

        termos_alocacao = ["atribuicao", "aulas", "jornada", "sessao", "sed", "ure", "saldo", "alocacao", "designacao"]
        termos_classificacao = ["pontuacao", "pontos", "classificacao", "vunesp", "titulos", "certificado", "mestrado", "doutorado", "especializacao"]

        if any(t in user_txt for t in termos_alocacao):
            return "alocacao"
        if any(t in user_txt for t in termos_classificacao):
            return "classificacao"

    return None

def _resgatar_intencao_tecnica(text):
    """
    Se o classificador falhar (disser 'fora_escopo'), esta função força
    o módulo correto se encontrar palavras-chave técnicas óbvias.
    """
    norm = _normalize_text(text)
    
    # 1. Avaliação
    if "qae" in norm or "farol" in norm or "indiciadores" in norm or "devolutiva" in norm:
        return "avaliacao"

    # 2. Classificação / Pontuação
    termos_classificacao = [
        "vunesp", "pontuacao", "pontos", "classificacao", "remanescente", 
        "diploma", "certificado", "mestrado", "doutorado", "titulos"
    ]
    if any(t in norm for t in termos_classificacao):
        return "classificacao"
    
    # 3. Alocação / PEI
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
                

                # OVERRIDE LEVE: se a pergunta tiver termos fortes de alocação, não deixa cair em classificacao
                norm = _normalize_text(last_message)
                if any(t in norm for t in ["atribuicao", "aulas", "sessao", "jornada", "sed", "ure", "saldo"]):
                    decision["modulo"] = "alocacao"
                    decision["sub_intencao"] = decision.get("sub_intencao") or "processo"
                    
                # Rede de Segurança
                if decision["modulo"] == "fora_escopo":
                    resgate = _resgatar_intencao_tecnica(last_message)
                    if resgate:
                        logging.info(f"RESGATE DE INTENÇÃO: Forçado de fora_escopo para {resgate}")
                        decision["modulo"] = resgate
                        decision["sub_intencao"] = "resgate_keyword"
                        decision_cmd = "CMD_TECNICA"
                    else:
                        if _verificar_critica_severa(last_message, classification=decision):
                            decision_cmd = "CMD_CRITICA_GRAVE"
                        else:
                            decision_cmd = "CMD_FORA_ESCOPO"
                else:
                    # Classificação Técnica Padrão
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
    
    # NOVO BLOCO: TRATAMENTO DE RECUSA / INSISTÊNCIA
    elif decision_cmd == "CMD_INSISTENCIA_ESCOLA":
        response_text = (
            "Compreendo, mas o **Trio Gestor da escola** é a primeira instância obrigatória "
            "para validação de dados e correção de apontamentos no sistema.\n\n"
            "Sem essa conferência inicial na unidade, a Diretoria de Ensino não consegue prosseguir. "
            "Por favor, tente esse contato inicial para garantir que sua solicitação siga o trâmite correto."
        )

    elif decision_cmd == "CMD_REGIONAL":
        response_text = (
            "Compreendo que o contato com a escola não resolveu a situação.\n\n"
            "Nesse caso, a escalação correta é procurar a **Unidade Regional de Ensino (URE)** responsável pela sua unidade. "
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
        # Fallback genérico - AQUI ESTÁ O FIX DO LOOP
        sub = decision.get("sub_intencao")
        emo = decision.get("emocao")
        
        if sub == "reclamacao_geral" or emo in ["frustracao", "raiva", "insatisfeito"]:
            # EM VEZ DE MANDAR PARA A ESCOLA CEGAMENTE, FAZ O CHECK
            response_text = (
               "Sinto muito pela sua insatisfação. Meu objetivo é apoiar com as regras técnicas.\n\n"
               "Para eu te orientar corretamente sobre como resolver esse problema: **você já conversou formalmente com o Trio Gestor da sua escola sobre isso?**"
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