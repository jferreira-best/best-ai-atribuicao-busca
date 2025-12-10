import os
import unicodedata
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list
from src.config.settings import MSG_ENCERRAMENTO_FORCADO

# ==============================================================================
# FUNÇÕES AUXILIARES DE ROBUSTEZ (NORMALIZAÇÃO)
# ==============================================================================

def normalizar_texto(texto):
    """
    Remove acentos, caracteres especiais e converte para minúsculo.
    Ex: "Estou com Dúvidas!" -> "estou com duvidas!"
    """
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower()

# Lista de Radicais (Pega o 'cerne' da palavra para ser robusto)
RADICAIS_SUPORTE = [
    "chamado", "abrir", "suporte", "ajuda", "socorro", 
    "entend", "reclam", "duvid", "confus", "errad", "incapaz", "problema"
]

def eh_intencao_suporte(query):
    """Verifica se algum radical de suporte está presente na query normalizada"""
    query_norm = normalizar_texto(query)
    return any(radical in query_norm for radical in RADICAIS_SUPORTE)

# ==============================================================================
# [NOVO] LÓGICA DE EXAUSTÃO / CIRCUIT BREAKER
# ==============================================================================

def verificar_exaustao(context_data: dict) -> bool:
    """
    Verifica se o usuário insiste após o sistema já ter dado a tratativa final.
    Retorna True se deve bloquear, False se pode continuar.
    """
    # Lista de sub-intenções que são consideradas "Fim de Papo"
    # Se o bot já passou por aqui na rodada anterior, ele não deve mais discutir.
    INTENCOES_FINAIS = [
        "suporte_entregar_link",      # Já deu o link do chamado
        "reportar_erro_dados",        # Já mandou falar com o Trio Gestor sobre dados
        "suporte_negar_atendimento"   # Já explicou que precisa do Trio antes
    ]
    
    # Tenta pegar o histórico ou a última ação do sistema vinda do Router/Orchestrator
    # Você precisará garantir que quem chama o run_chain envie esse dado
    historico = context_data.get("historico_intencoes", []) 
    ultima_acao = context_data.get("ultima_sub_intencao_sistema", "")

    # Lógica 1: Se a última coisa que o sistema fez foi uma ação final
    if ultima_acao in INTENCOES_FINAIS:
        return True
        
    # Lógica 2 (Opcional): Se o usuário já caiu em "suporte_insistencia" mais de 2 vezes
    contador_insistencia = historico.count("suporte_insistencia")
    if contador_insistencia >= 3:
        return True
        
    return False
# ==============================================================================
# FUNÇÃO PRINCIPAL DO MÓDULO
# ==============================================================================

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    sub_intencao = intent.get("sub_intencao", "")
    
    # -------------------------------------------------------------------------
    # [NOVO] PASSO 0: CHECK DE EXAUSTÃO (Prioridade Máxima)
    # Antes de verificar qual é a sub_intenção atual, verifica se devemos parar.
    # -------------------------------------------------------------------------
    if verificar_exaustao(context_data):
        return {
            "resposta": MSG_ENCERRAMENTO_FORCADO,
            "modulo": "avaliacao",
            "fontes": ["Sistema | Encerramento"],
            "debug_intent": intent,
            "stop_conversation": True # Flag útil para o frontend saber que acabou
        }


    docs = []

    # =========================================================================
    # LÓGICA DE INTERATIVIDADE E SUPORTE
    # Define o contexto sintético com base no estado da conversa (vindo do Router)
    # =========================================================================
    # 0. NOVA REGRA: DISCREPÂNCIA DE DADOS (Prioridade Alta)
    if sub_intencao == "reportar_erro_dados":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário está relatando uma inconsistência de dados (ex: presença ou notas que divergem da realidade).
            NÃO tente explicar a regra de cálculo, pois o dado de origem está supostamente errado.
            
            RESPOSTA PADRÃO OBRIGATÓRIA:
            "Como o sistema é automatizado, se os dados apresentados (como presença ou notas) divergem da realidade, isso deve ser tratado como uma correção de dados no sistema. O procedimento é acionar o Trio Gestor na sua unidade escolar para que verifiquem o lançamento e, se necessário, abram um chamado de correção."
            """,
            "meta": "Sistema de Suporte | Tipo: Orientação de Dados"
        }]
        # Forçamos temperatura baixa para garantir fidelidade à mensagem
        intent["sub_intencao"] = "suporte_dados"
    # 1. Fase da Pergunta (O Router identificou início de suporte via status)
    elif sub_intencao == "suporte_perguntar_trio":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário quer abrir um chamado, tirar dúvidas ou precisa de suporte.
            Sua tarefa é EXCLUSIVAMENTE perguntar se ele já acionou o Trio Gestor.
            Responda exatamente com esta pergunta: 
            "Para prosseguir com sua solicitação, preciso confirmar: O Gerente de Organização Escolar ou outro membro do trio gestor já foi acionado para tratar da sua solicitação? (Responda Sim ou Não)"
            Não dê o link ainda.
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]

    # 2. Fase do Link (Usuário disse SIM e o Router detectou)
    elif sub_intencao == "suporte_entregar_link":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário confirmou que JÁ falou com o Trio Gestor.
            Você deve fornecer o link de abertura de chamado agora.
            Link: https://atendimento.educacao.sp.gov.br/support/nova-ocorrencia-see/
            Seja cordial e finalize o atendimento.
            """,
            "meta": "Sistema de Suporte | Tipo: Link"
        }]

    # 3. Fase da Negação (Usuário disse NÃO e o Router detectou)
    elif sub_intencao == "suporte_negar_atendimento":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário informou que AINDA NÃO falou com o Trio Gestor.
            Oriente educadamente que, antes de abrir um chamado técnico, ele deve procurar o Trio Gestor (Gerente de Organização Escolar) na unidade escolar para uma primeira tratativa.
            Não forneça o link.
            """,
            "meta": "Sistema de Suporte | Tipo: Orientação"
        }]

    # 4. Fallback de Suporte (Robustez: Caso o Router não tenha pego, mas a frase contenha palavras de ajuda)
    # Aqui usamos a função inteligente 'eh_intencao_suporte'
    elif eh_intencao_suporte(query):
         docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário expressou dúvida, confusão ou necessidade de ajuda.
            Ignore regras técnicas complexas.
            Pergunte se ele já acionou o Trio Gestor na escola para tentar resolver o caso.
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]
         # Força a sub_intenção para o prompt saber que é suporte e usar temp baixa
         sub_intencao = "suporte_insistencia"

    # 5. Fluxo Normal (RAG Técnico)
    else:
        # Só faz a busca vetorial se NÃO for nenhum caso de suporte acima
        docs = rag_core.retrieve_context(query, top_k=5)

    # =========================================================================

    # Formata contexto para string
    context_str = "\n\n".join([f"[{d['meta']}]\n{d['content']}" for d in docs])
    
    # Carrega Prompt Específico
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompt_path = os.path.join(base_dir, "prompts", "avaliacao.md")
    
    # Leitura do prompt
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = "Responda com base no contexto: {contexto}\nPergunta: {pergunta}"
        
    # Injeção de Variáveis
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    final_prompt = final_prompt.replace("{sub_intencao}", str(sub_intencao))
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", "neutro"))
    
    # Geração da Resposta via LLM
    messages = [{"role": "user", "content": final_prompt}]
    
    # Temperatura:
    # 0.1 para Suporte (robótico/preciso)
    # 0.2 para Técnico (preciso, mas fluente)
    temp = 0.1 if "suporte" in str(sub_intencao) or sub_intencao == "reportar_erro_dados" else 0.2
    
    # Max Tokens 800 para respostas concisas e diretas
    resp, _, text = call_api_with_messages(messages, max_tokens=800, temperature=temp)
    
    # Limpeza dos metadados (Remove | Tipo: Portaria, etc)
    raw_sources = [d['meta'] for d in docs]
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "avaliacao",
        "fontes": deduplicate_list(cleaned_sources),
        "debug_intent": intent
    }