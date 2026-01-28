import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from src.config import settings
from src.shared.utils import clean_text, filename_from_source

# --- Embeddings ---
def _get_embedding(text):
    """Gera embedding usando Azure OpenAI"""
    if not text: return None
    try:
        url = f"{settings.AOAI_ENDPOINT}/openai/deployments/{settings.AOAI_EMB_DEPLOYMENT}/embeddings?api-version={settings.AOAI_API_VERSION}"
        headers = {"api-key": settings.AOAI_API_KEY, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json={"input": text}, timeout=settings.HTTP_TIMEOUT_SHORT)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        logging.error(f"Erro embedding: {e}")
        return None

# --- Buscas ---
# --- Buscas ---
def _vector_search(vector, top_k):
    if not vector: return []
    
    try:
        k_param = int(top_k) 
    except:
        k_param = 5
    
    url = f"{settings.SEARCH_ENDPOINT}/indexes/{settings.SEARCH_INDEX}/docs/search?api-version={settings.SEARCH_API_VERSION}"
    
    payload = {
        "vectorQueries": [{
            "kind": "vector", 
            "vector": vector, 
            "k": k_param,
            "fields": "content_vector"
        }],
        "top": k_param,
        # CORREÇÃO ABAIXO: Removido 'content', mantido apenas 'text'
        "select": "id, doc_title, text, source_file, norma_tipo, data_publicacao, assunto" 
    }
    
    try:
        r = requests.post(url, headers={"api-key": settings.SEARCH_KEY, "Content-Type": "application/json"}, json=payload)
        r.raise_for_status()
        return r.json().get("value", [])
    except Exception as e:
        logging.error(f"Erro vector_search: {e}")
        return []

def _text_search(query, top_k):
    url = f"{settings.SEARCH_ENDPOINT}/indexes/{settings.SEARCH_INDEX}/docs/search?api-version={settings.SEARCH_API_VERSION}"
    payload = {
        "search": query,
        "top": top_k,
        # CORREÇÃO: Apenas campos que existem no índice (SEM 'content')
        "select": "id, doc_title, text, source_file, norma_tipo, data_publicacao, assunto",
        "queryType": "semantic",
        "semanticConfiguration": settings.SEARCH_SEMANTIC_CONFIG,
        "captions": "extractive",
        "answers": "extractive|count-3",
        "queryLanguage": "pt-br"
    }
    try:
        r = requests.post(url, headers={"api-key": settings.SEARCH_KEY, "Content-Type": "application/json"}, json=payload)
        r.raise_for_status()
        return r.json().get("value", [])
    except Exception as e:
        logging.error(f"Erro text_search: {e}")
        return []

# --- Core RAG ---
def retrieve_context(user_query: str, top_k: int = 10):
    """
    Executa busca Híbrida (Vetorial + Semântica) e retorna contexto enriquecido
    com metadados de data para decisão inteligente do LLM.
    """
    
    # 1. Paraleliza Embedding e Busca Texto
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_emb = executor.submit(_get_embedding, user_query)
        future_text = executor.submit(_text_search, user_query, top_k)
        
        vector = future_emb.result()
        text_hits = future_text.result()
        
        # Só roda busca vetorial se embedding funcionou
        vec_hits = []
        if vector:
            vec_hits = _vector_search(vector, top_k)

    # 2. Diagnóstico Rápido (Log)
    logging.info(f"Hits Texto: {len(text_hits)} | Hits Vetor: {len(vec_hits)}")
    if text_hits:
        first = text_hits[0]
        rerank_score = first.get('@search.rerankerScore', 'N/A')
        logging.info(f"Top Hit Score (Reranker): {rerank_score}")

    # 3. Deduplicação (Merge Híbrido)
    all_hits = {}
    
    # Prioridade para Semantic Ranker (Hits de Texto)
    for h in text_hits:
        all_hits[h['id']] = h
        
    # Completa com Vetorial (se ID for inédito)
    for h in vec_hits:
        if h['id'] not in all_hits:
            all_hits[h['id']] = h

    # 4. Montagem do Contexto Rico
    context_docs = []
    
    # Ordena novamente pelo Reranker Score (se disponível) ou Score padrão
    sorted_hits = sorted(
        all_hits.values(), 
        key=lambda x: x.get('@search.rerankerScore') or x.get('@search.score') or 0, 
        reverse=True
    )

    for h in sorted_hits[:top_k]: # Garante top_k final após merge
        
        # Metadados Essenciais para Hierarquia de Normas
        src_file = filename_from_source(h.get('source_file'))
        doc_title = h.get('doc_title') or src_file
        data_pub = h.get('data_publicacao', 'Data Desconhecida')
        tipo = h.get('norma_tipo', 'Norma')
        assunto = h.get('assunto', 'Geral')
        
        # Limpeza do texto
        raw_content = h.get('content') or h.get('text') or ""
        clean_content = clean_text(raw_content)
        
        # Bloco formatado para o LLM entender a hierarquia
        # Isso permite que o prompt diga: "Priorize a data mais recente"
        meta_block = (
            f"Documento: {doc_title}\n"
            f"Arquivo Original: {src_file}\n"
            f"Data Publicação: {data_pub}\n"
            f"Tipo Normativo: {tipo}\n"
            f"Assunto: {assunto}"
        )
        
        # Formata o chunk final
        formatted_entry = f"--- INÍCIO DO DOCUMENTO ---\n{meta_block}\n\nCONTEÚDO:\n{clean_content}\n--- FIM DO DOCUMENTO ---\n"
        
        context_docs.append({
            "content": formatted_entry,
            "meta": src_file,  # Usado apenas para citação final ao usuário
            "score": h.get('@search.rerankerScore')
        })

    return context_docs