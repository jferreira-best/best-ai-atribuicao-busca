import os
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    query_lower = query.lower()
    
    # =========================================================================
    # --- LÓGICA DE PRIORIDADE DE SUPORTE ---
    # Se for identificado como suporte (pelo Router ou por palavras-chave),
    # nós IGNORAMOS a busca vetorial para não "sujar" a cabeça do LLM com 
    # regras técnicas que não tem a ver com o pedido de ajuda.
    # =========================================================================
    termos_suporte = ["chamado", "abrir chamado", "suporte", "ajuda", "não entendi", "nao entendi", "reclamar", "discordo", "preciso de ajuda"]
    
    # Verifica se veio marcado do Router OU se tem a palavra-chave
    eh_suporte = (intent.get("sub_intencao") == "suporte_insistencia") or \
                 any(t in query_lower for t in termos_suporte)

    if eh_suporte:
        # FORÇA O CONTEXTO SINTÉTICO (Sobrescreve qualquer busca)
        docs = [{
            "content": """
            DIRETRIZ DE SISTEMA PRIORITÁRIA:
            O usuário está confuso, precisa de ajuda ou quer abrir um chamado.
            NÃO explique regras de avaliação. NÃO explique cálculos.
            Sua ÚNICA função agora é orientar o usuário a procurar o Trio Gestor ou abrir um chamado, conforme a regra de 'Conclusão e Encaminhamento' do seu prompt.
            Seja breve e direto.
            """,
            "meta": "Instrução de Suporte | Tipo: Sistema"
        }]
    else:
        # Só faz a busca no banco de dados se NÃO for suporte
        docs = rag_core.retrieve_context(query, top_k=5)
    # =========================================================================

    # Formata contexto para string
    context_str = "\n\n".join([f"[{d['meta']}]\n{d['content']}" for d in docs])
    
    # 2. Carrega Prompt Específico
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompt_path = os.path.join(base_dir, "prompts", "avaliacao.md")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
        
    # 3. Injeção de Variáveis
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    # Garante que a sub_intencao vá como suporte se foi detectado aqui
    sub_intencao = "suporte_insistencia" if eh_suporte else intent.get("sub_intencao", "")
    final_prompt = final_prompt.replace("{sub_intencao}", sub_intencao)
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", ""))
    
    # 4. Geração da Resposta
    messages = [{"role": "user", "content": final_prompt}]
    resp, _, text = call_api_with_messages(messages, max_tokens=800, temperature=0.3)
    
    # Limpeza dos metadados 
    raw_sources = [d['meta'] for d in docs]
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "avaliacao",
        "fontes": deduplicate_list(cleaned_sources),
        "debug_intent": intent
    }