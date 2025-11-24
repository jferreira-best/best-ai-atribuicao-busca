import os
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    raw_body = context_data.get("raw_body", {})
    # ... Lógica idêntica ao avaliacao.py, mas carregando 'classificacao.md' ...
    # Para brevidade, repita o padrão acima alterando o arquivo do prompt.
    
    #docs = rag_core.retrieve_context(query, top_k=5)
    docs = rag_core.retrieve_context(
        query, 
        top_k=raw_body.get("topK", 5),
        semantic_config=raw_body.get("semantic_config") # <--- O Pulo do Gato
    )

    context_str = "\n\n".join([f"[{d['meta']}]\n{d['content']}" for d in docs])
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompt_path = os.path.join(base_dir, "prompts", "classificacao.md")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
        
    #final_prompt = template.replace("{pergunta}", query).replace("{contexto}", context_str)
    final_prompt = template.replace("{pergunta}", query)
    final_prompt = final_prompt.replace("{contexto}", context_str)
    final_prompt = final_prompt.replace("{sub_intencao}", intent.get("sub_intencao", ""))
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", ""))


    messages = [{"role": "user", "content": final_prompt}]
    resp, _, text = call_api_with_messages(messages, max_tokens=800)
    
    return {
        "resposta": text,
        "modulo": "classificação",
        "fontes": deduplicate_list([d['meta'] for d in docs]), # <--- AQUI: Envolva a lista com a função
        "debug_intent": intent
    }