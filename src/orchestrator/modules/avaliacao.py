import os
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    sub_intencao = intent.get("sub_intencao", "")
    query_lower = query.lower()
    
    docs = []

    # =========================================================================
    # LÓGICA DE INTERATIVIDADE E SUPORTE
    # Define o contexto sintético com base no estado da conversa (vindo do Router)
    # =========================================================================
    
    # 1. Fase da Pergunta (O Router identificou início de suporte)
    if sub_intencao == "suporte_perguntar_trio":
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário quer abrir um chamado ou precisa de suporte.
            Sua tarefa é EXCLUSIVAMENTE perguntar se ele já acionou o Trio Gestor.
            Responda exatamente com esta pergunta: 
            "Para prosseguir com a abertura do chamado, preciso confirmar: O Gerente de Organização Escolar ou outro membro do trio gestor já foi acionado para tratar da sua solicitação? (Responda Sim ou Não)"
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

    # 4. Fallback de Suporte (Caso o Router não tenha pego pela máquina de estados, mas seja suporte)
    elif any(t in query_lower for t in ["chamado", "abrir chamado", "suporte", "ajuda", "não entendi", "nao entendi", "reclamar"]):
         docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário parece querer ajuda ou suporte.
            Pergunte se ele já acionou o Trio Gestor na escola antes de prosseguir.
            """,
            "meta": "Sistema de Suporte | Tipo: Instrução"
        }]
         # Força a sub_intenção para o prompt saber que é suporte
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
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
        
    # Injeção de Variáveis
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    final_prompt = final_prompt.replace("{sub_intencao}", str(sub_intencao))
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", "neutro"))
    
    # Geração da Resposta via LLM
    messages = [{"role": "user", "content": final_prompt}]
    
    # Temperatura baixa para seguir as instruções de suporte rigorosamente
    temp = 0.1 if "suporte" in str(sub_intencao) else 0.2
    
    resp, _, text = call_api_with_messages(messages, max_tokens=800, temperature=temp)
    
    # Limpeza dos metadados
    raw_sources = [d['meta'] for d in docs]
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "avaliacao",
        "fontes": deduplicate_list(cleaned_sources),
        "debug_intent": intent
    }