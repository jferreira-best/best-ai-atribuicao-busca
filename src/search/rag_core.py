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
def _vector_search(vector, top_k):
    if not vector: return []
    url = f"{settings.SEARCH_ENDPOINT}/indexes/{settings.SEARCH_INDEX}/docs/search?api-version={settings.SEARCH_API_VERSION}"
    payload = {
        "vectorQueries": [{"kind": "vector", "vector": vector, "k": top_k, "fields": "content_vector"}],
        "top": top_k
    }
    try:
        r = requests.post(url, headers={"api-key": settings.SEARCH_KEY}, json=payload, timeout=settings.HTTP_TIMEOUT_LONG)
        return r.json().get("value", [])
    except Exception as e:
        logging.error(f"Erro Vector Search: {e}")
        return []

def _text_search(query, top_k, semantic_config=None):
    url = f"{settings.SEARCH_ENDPOINT}/indexes/{settings.SEARCH_INDEX}/docs/search?api-version={settings.SEARCH_API_VERSION}"
    
    # Usa a config do payload ou o default do settings
    config_to_use = semantic_config or settings.SEMANTIC_CONFIG
    
    #payload = {"search": query, "top": top_k}

    payload = {
        "search": query,
        "top": top_k,
        "select": "content, title, source_file, norma_tipo" # Traga SÓ o necessário
    }


    
    if settings.ENABLE_SEMANTIC and config_to_use:
        payload.update({
            "queryType": "semantic",
            "semanticConfiguration": config_to_use, # <--- Usa a config dinâmica
            "captions": "extractive",
            "answers": "extractive|count-3" # Tenta extrair respostas diretas
        })
        
    try:
        r = requests.post(url, headers={"api-key": settings.SEARCH_KEY}, json=payload, timeout=settings.HTTP_TIMEOUT_LONG)
        return r.json().get("value", [])
    except Exception as e:
        logging.error(f"Erro Text Search: {e}")
        return []

# Atualize a função principal para aceitar **kwargs
def retrieve_context(query: str, top_k=5, **kwargs) -> list:
    """
    Executa busca híbrida.
    kwargs pode conter 'semantic_config' vindo do body da requisição.
    """
    sem_config = kwargs.get('semantic_config')
    
    # 1. Embeddings
    vector = _get_embedding(query)
    
    # 2. Busca Paralela
    with ThreadPoolExecutor() as executor:
        fut_vec = executor.submit(_vector_search, vector, top_k)
        # Passamos a config dinâmica aqui
        fut_text = executor.submit(_text_search, query, top_k, semantic_config=sem_config)
        
        vec_hits = fut_vec.result()
        text_hits = fut_text.result()

    # --- LOG DE PROVA DE CONCEITO ---
    print(f"\n--- DIAGNÓSTICO DE BUSCA ---")
    print(f"Hits Vetoriais: {len(vec_hits)}")
    print(f"Hits Texto/Semântico: {len(text_hits)}")
    
    if text_hits:
        first = text_hits[0]
        rerank_score = first.get('@search.rerankerScore', 'N/A')
        captions = first.get('@search.captions')
        print(f"Top Hit Score (Reranker): {rerank_score} (Se > 0, Semântico está ATIVO)")
        if captions:
            print(f" Caption Semântico gerado: Sim")
    print("----------------------------\n")
    # --------------------------------

    # 3. Deduplicação (Merge Híbrido)
    # O Reranker Score é a "prova real" da busca semântica. Priorizamos ele.
    all_hits = {}
    
    # Adiciona hits de texto (que trazem o rerankerScore)
    for h in text_hits:
        all_hits[h['id']] = h
        
    # Adiciona hits vetoriais (se já não existirem, o vetor serve de backup/enrichment)
    for h in vec_hits:
        if h['id'] not in all_hits:
            all_hits[h['id']] = h

    context_docs = []
    for h in all_hits.values():
        meta = f"Fonte: {filename_from_source(h.get('source_file'))} | Tipo: {h.get('norma_tipo', 'N/A')}"
        text = clean_text(h.get('content') or h.get('text') or "")
        
        # Captura o score para ordenação
        final_score = h.get('@search.rerankerScore') or h.get('@search.score') or 0
        
        context_docs.append({
            "content": text,
            "meta": meta,
            "score": final_score
        })
    
    # Ordena pelo Reranker Score (maior é melhor)
    return sorted(context_docs, key=lambda x: x['score'], reverse=True)[:top_k]