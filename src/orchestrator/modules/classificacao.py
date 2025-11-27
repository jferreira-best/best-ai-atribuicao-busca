import os
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    query_lower = query.lower()
    
    # 1. Recuperação (RAG)
    docs = rag_core.retrieve_context(query, top_k=6)

    # Formata contexto para string
    context_str = "\n\n".join([f"[{d['meta']}]\n{d['content']}" for d in docs])
    
    # 2. Carrega Prompt Específico
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompt_path = os.path.join(base_dir, "prompts", "classificacao.md")
    
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        template = "Responda com base no contexto: {contexto}\nPergunta: {pergunta}"
        
    # 3. Injeção de Variáveis
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    final_prompt = final_prompt.replace("{sub_intencao}", intent.get("sub_intencao", "geral"))
    
    # 4. Geração da Resposta
    messages = [{"role": "user", "content": final_prompt}]
    
    # Temperatura 0.0 ou 0.1 para garantir precisão matemática nas tabelas
    # Max Tokens 2000 para permitir explicações longas e detalhadas
    resp, _, text = call_api_with_messages(messages, max_tokens=1500, temperature=0.0)
    
    # Limpeza dos metadados
    raw_sources = [d['meta'] for d in docs]
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "classificacao",
        "fontes": deduplicate_list(cleaned_sources),
        "debug_intent": intent
    }