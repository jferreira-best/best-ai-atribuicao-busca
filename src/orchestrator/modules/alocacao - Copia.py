import os
import unicodedata
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def normalizar_texto(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower()

# --- LISTA EXPANDIDA PARA PEGAR ERROS DE TELA ---
RADICAIS_SUPORTE = [
    "chamado", "abrir", "suporte", "ajuda", "socorro", 
    "entend", "reclam", "duvid", "confus", "errad", "incapaz", "problema",
    "travad", "travou", "nao consigo", "erro", "falha", "bug", "fora do ar",
    "visualiza", "aparece", "sumiu", "acesso", "login"
]

def eh_intencao_suporte(query):
    query_norm = normalizar_texto(query)
    return any(radical in query_norm for radical in RADICAIS_SUPORTE)

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    sub_intencao = intent.get("sub_intencao", "")
    
    docs = []

    # 1. Fase da Pergunta (Router)
    if sub_intencao == "suporte_perguntar_trio":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário relatou um problema técnico ou de processo.
            Sua tarefa é EXCLUSIVAMENTE perguntar se ele já acionou o Trio Gestor.
            Responda: "Para prosseguir com sua solicitação, preciso confirmar: O Gerente de Organização Escolar ou o Diretor já foi acionado para verificar esse caso? (Responda Sim ou Não)"
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]

    # 2. Fase do Link
    elif sub_intencao == "suporte_entregar_link":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário confirmou contato com a escola.
            Forneça o link de abertura de chamado: https://atendimento.educacao.sp.gov.br/support/nova-ocorrencia-see/
            """,
            "meta": "Sistema de Suporte | Tipo: Link"
        }]

    # 3. Fase da Negação
    elif sub_intencao == "suporte_negar_atendimento":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            Oriente que questões de sistema e atribuição devem ser reportadas primeiramente na Unidade Escolar.
            """,
            "meta": "Sistema de Suporte | Tipo: Orientação"
        }]

    # 4. Fallback de Suporte (Agora pega "visualizar" e "sumiu")
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

    # 5. Fluxo Normal (RAG Técnico)
    else:
        docs = rag_core.retrieve_context(query, top_k=6)

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

    temp = 0.1 if "suporte" in str(sub_intencao) else 0.2

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