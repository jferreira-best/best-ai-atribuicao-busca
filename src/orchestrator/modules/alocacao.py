import os
import unicodedata
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list
from src.config.settings import MSG_ENCERRAMENTO_FORCADO

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def normalizar_texto(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower()

# --- LISTA EXPANDIDA PARA PEGAR ERROS DE TELA ---
RADICAIS_SUPORTE = [
    "chamado", "abrir", "suporte", "ajuda", "socorro", 
    "entend", "reclam", "duvid", "confus", "errad", "incapaz", "problema",
    "travad", "travou", "nao consigo", "erro", "falha", "bug", "fora do ar",
    "visualiza", "aparece", "sumiu", "acesso", "login","inconsiste", 
    "incorret", "errad", "nao bate", "nao condiz", "divergen", "sumiu", "painel"
]

def eh_intencao_suporte(query):
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
# FUNÇÃO PRINCIPAL
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
    # 1. Fase da Pergunta (Router mandou perguntar)
    elif sub_intencao == "suporte_perguntar_trio":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário relatou um problema técnico ou de processo (ex: não visualiza, sistema travado).
            Sua tarefa é EXCLUSIVAMENTE perguntar se ele já acionou o Trio Gestor.
            Responda: "Para prosseguir com sua solicitação, preciso confirmar: O Gerente de Organização Escolar ou o Diretor já foi acionado para verificar esse caso? (Responda Sim ou Não)"
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]

    # 2. Fase do Link (Usuário disse SIM)
    elif sub_intencao == "suporte_entregar_link":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário confirmou contato com a escola.
            Forneça o link de abertura de chamado: https://atendimento.educacao.sp.gov.br/support/nova-ocorrencia-see/
            """,
            "meta": "Sistema de Suporte | Tipo: Link"
        }]

    # 3. Fase da Negação (Usuário disse NÃO)
    elif sub_intencao == "suporte_negar_atendimento":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário NÃO falou com a escola ainda.
            Oriente que questões de sistema e atribuição devem ser reportadas primeiramente na Unidade Escolar (Trio Gestor).
            """,
            "meta": "Sistema de Suporte | Tipo: Orientação"
        }]

    # 4. Fallback de Suporte (Captura "visualizar", "sumiu", "travado")
    elif eh_intencao_suporte(query):
         docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário relatou dificuldade técnica ou dúvida ("não consigo", "erro", "não visualizo").
            Ignore regras de portaria.
            Pergunte se ele já acionou o Trio Gestor na escola para tentar resolver.
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]
         sub_intencao = "suporte_insistencia"

    # 5. Fluxo Normal (RAG Técnico - PEI/Regular)
    else:
        docs = rag_core.retrieve_context(query, top_k=12)

    # =========================================================================

    context_str = "\n\n".join([f"[{d['meta']}]\n{d['content']}" for d in docs])
    
    # Carrega Prompt
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompt_path = os.path.join(base_dir, "prompts", "alocacao.md")
    
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = "Contexto: {contexto}\nPergunta: {pergunta}"
        
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    final_prompt = final_prompt.replace("{sub_intencao}", str(sub_intencao))
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", "neutro"))

    # Ajuste de temperatura
    temp = 0.1 if "suporte" in str(sub_intencao) or sub_intencao == "reportar_erro_dados" else 0.2

    messages = [{"role": "user", "content": final_prompt}]
    resp, _, text = call_api_with_messages(messages, max_tokens=900, temperature=temp)
    
    raw_sources = [d['meta'] for d in docs]
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "alocacao",
        "fontes": deduplicate_list(cleaned_sources),
        "debug_intent": intent
    }