import os
from src.search import rag_core
from src.shared.llm import call_api_with_messages
from src.shared.utils import deduplicate_list

def run_chain(query: str, context_data: dict):
    intent = context_data.get("intent", {})
    
    # 1. Recuperação (RAG)
    docs = rag_core.retrieve_context(query, top_k=5)
    
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
    final_prompt = final_prompt.replace("{sub_intencao}", intent.get("sub_intencao", ""))
    final_prompt = final_prompt.replace("{emocao}", intent.get("emocao", ""))
    
    # 4. Geração da Resposta
    messages = [{"role": "user", "content": final_prompt}]
    resp, _, text = call_api_with_messages(messages, max_tokens=800, temperature=0.3)
    
    # Limpeza dos metadados antes de enviar para o retorno
    raw_sources = [d['meta'] for d in docs]
    # Faz o split pelo pipe '|' e pega apenas a primeira parte (o nome do arquivo)
    cleaned_sources = [s.split('|')[0].strip() for s in raw_sources]

    return {
        "resposta": text,
        "modulo": "avaliacao",
        "fontes": deduplicate_list(cleaned_sources), 
        "debug_intent": intent
    }