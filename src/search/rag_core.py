import requests
import logging
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from src.config import settings
from src.shared.utils import clean_text, filename_from_source

# Configuração de Log
logging.getLogger().setLevel(logging.INFO)

# --- Embeddings ---
def _get_embedding(text):
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
    try:
        k_param = 50 # Busca ampla para garantir recall
    except:
        k_param = 50
    
    url = f"{settings.SEARCH_ENDPOINT}/indexes/{settings.SEARCH_INDEX}/docs/search?api-version={settings.SEARCH_API_VERSION}"
    payload = {
        "vectorQueries": [{
            "kind": "vector", "vector": vector, "k": k_param, "fields": "content_vector"
        }],
        "top": k_param,
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

# --- Lógica de Negócio ---
def _expand_query(user_query: str) -> str:
    if not user_query: return user_query
    q = user_query.lower()
    
    # Gatilhos EXCLUSIVOS de Atribuição (Só aqui forçamos 2026)
    gatilhos_at = [
        "contratado", "candidato", "contratação", "categoria o", 
        "jornada", "carga", "projeto", "programa", "atribuição", "adido"
    ]
    
    # Gatilhos de Avaliação (Não forçamos ano, pois as regras podem ser de 2025)
    gatilhos_ad = ["farol", "avaliação", "desempenho", "indicador", "qae", "qse"]

    if any(t in q for t in gatilhos_at) and not any(t in q for t in gatilhos_ad):
        return f"{user_query} regras vigentes 2026 nova redação (N.R.) resolução 10"
    
    return user_query

# --- Helpers Matemáticos ---

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

def _parse_date_robust(data_iso: str, filename: str):
    if data_iso:
        clean = str(data_iso).strip()
        if "T" in clean: clean = clean.split("T")[0]
        try:
            return datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except: pass

    if filename:
        match = re.search(r"(\d{1,2})\s+de\s+([a-zA-Zç]+)\s+(?:de\s+)?(\d{4})", filename, re.IGNORECASE)
        if match:
            dia, mes_nome, ano = match.groups()
            mes_num = MESES_PT.get(mes_nome.lower())
            if mes_num:
                try:
                    return datetime(int(ano), mes_num, int(dia), tzinfo=timezone.utc)
                except: pass
    return None

def _recency_score(data_publicacao: str, source_file: str) -> float:
    d = _parse_date_robust(data_publicacao, source_file)
    if not d: return 0.0

    now = datetime.now(timezone.utc)
    days_diff = max((now - d).days, 0)
    
    bonus = 0.0
    # Mantemos a agressividade para Atribuição, mas o Context Match vai salvar a Avaliação
    if days_diff <= 7: bonus += 5.0
    elif days_diff <= 20: bonus += 3.0
    elif days_diff <= 45: bonus += 1.5
    
    if d.year >= 2026: bonus += 0.5
    return bonus

def _context_match_bonus(doc_title: str, source_file: str, user_query: str) -> float:
    """
    [NOVO] O Salva-Vidas:
    Se a pergunta é de Avaliação, força arquivos 'AD -' para o topo, 
    mesmo que sejam 'velhos' (2025).
    """
    txt_check = (doc_title or "") + " " + (source_file or "")
    t = txt_check.lower()
    q = user_query.lower()
    
    # 1. Contexto AVALIAÇÃO DE DESEMPENHO (AD)
    # Se perguntar de farol, indicadores, avaliação...
    termos_ad = ["farol", "avaliação", "avaliacao", "desempenho", "indicador", "meta", "ponto", "qae", "qse"]
    
    if any(kw in q for kw in termos_ad):
        # Se o arquivo for do tipo AD (Avaliação) ou tiver Avaliação no nome
        if "ad -" in t or "avaliação" in t or "avaliacao" in t or "portaria conjunta" in t:
            return 15.0  # BÔNUS MASSIVO (Supera qualquer recência de 2026)

    # 2. Contexto ATRIBUIÇÃO (AT) - Reforço
    termos_at = ["atribuição", "atribuicao", "jornada", "carga", "constituição", "adido", "saldo"]
    if any(kw in q for kw in termos_at):
        if "at -" in t or "resolução" in t:
            return 5.0

    return 0.0

def _content_type_bonus(text_snippet: str, data_publicacao: str, source_file: str) -> float:
    if not text_snippet: return 0.0
    
    d = _parse_date_robust(data_publicacao, source_file)
    # Trava de segurança: "Nova Redação" só vale se for de 2026+
    if not d or d.year < 2026:
        return 0.0 

    t = text_snippet.lower()[:3000]
    gatilhos = ["passam a vigorar", "nova redação", "(n. r.)", "(n.r.)", "altera dispositivos"]
    
    if any(g in t for g in gatilhos):
        return 10.0 # O Martelo da Resolução 10
        
    return 0.0

def _authority_score(doc_title: str, norma_tipo: str) -> float:
    t = (doc_title or "").lower()
    nt = (norma_tipo or "").lower()
    score = 0.0
    if "resolu" in t or "resolu" in nt: score += 0.5
    elif "portaria" in t or "portaria" in nt: score += 0.3
    return score

# --- Core RAG ---
def retrieve_context(user_query: str, top_k: int = 10):
    expanded_query = _expand_query(user_query)
    internal_k = 50 

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_emb = executor.submit(_get_embedding, expanded_query)
        future_text = executor.submit(_text_search, expanded_query, internal_k)
        vector = future_emb.result()
        text_hits = future_text.result()
        
        vec_hits = []
        if vector: vec_hits = _vector_search(vector, internal_k)

    all_hits = {}
    for h in text_hits: all_hits[h['id']] = h
    for h in vec_hits:
        if h['id'] not in all_hits: all_hits[h['id']] = h

    logging.warning(f"--- RAIO-X HIBRIDO (Query: {user_query}) ---")
    
    scored_candidates = []
    
    for h in all_hits.values():
        src = filename_from_source(h.get('source_file'))
        doc_title = h.get('doc_title') or src
        
        # Scores
        base = (h.get('@search.rerankerScore') or h.get('@search.score') or 0)
        recency = _recency_score(h.get("data_publicacao"), h.get("source_file"))
        auth = _authority_score(doc_title, h.get("norma_tipo"))
        content = _content_type_bonus(h.get("content") or h.get("text"), h.get("data_publicacao"), h.get("source_file"))
        
        # O NOVO BÔNUS DE CONTEXTO (Muda o jogo para Avaliação)
        context_match = _context_match_bonus(doc_title, h.get("source_file"), user_query)
        
        final_score = base + recency + auth + content + context_match
        
        h['_final_score'] = final_score
        
        scored_candidates.append({
            "doc": src[:30], 
            "base": round(base, 2),
            "rec": recency,
            "ctx": context_match, # Verifique esta coluna no log!
            "FINAL": round(final_score, 2)
        })

    # Logs Visuais
    scored_candidates.sort(key=lambda x: x['FINAL'], reverse=True)
    print("\n" + "="*80)
    print(f"{'DOCUMENTO':<30} | {'BASE':<6} | {'REC':<5} | {'CTX':<5} | {'TOTAL'}")
    print("-" * 80)
    for c in scored_candidates[:12]:
        print(f"{c['doc']:<30} | {c['base']:<6} | {c['rec']:<5} | {c['ctx']:<5} | {c['FINAL']}")
    print("="*80 + "\n")

    sorted_hits = sorted(all_hits.values(), key=lambda x: x['_final_score'], reverse=True)

    context_docs = []
    for h in sorted_hits[:top_k]:
        src_file = filename_from_source(h.get('source_file'))
        doc_title = h.get('doc_title') or src_file
        data_raw = h.get('data_publicacao')
        d_obj = _parse_date_robust(data_raw, src_file)
        dt_str = d_obj.strftime("%d/%m/%Y") if d_obj else (data_raw or "Data Desconhecida")
        
        formatted_entry = (
            f"--- DOC ---\n"
            f"Documento: {doc_title}\n"
            f"Arquivo: {src_file}\n"
            f"Data: {dt_str}\n"
            f"Score: {h['_final_score']:.2f}\n\n"
            f"CONTEÚDO:\n{clean_text(h.get('content') or h.get('text') or '')}\n"
            f"--- FIM DOC ---\n"
        )
        
        context_docs.append({
            "content": formatted_entry,
            "meta": src_file,
            "score": h['_final_score']
        })

    return context_docs