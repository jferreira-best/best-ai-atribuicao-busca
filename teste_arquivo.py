import os
import requests
from collections import Counter
import os
import json

def load_local_settings(path="local.settings.json"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    values = data.get("Values", {})
    for k, v in values.items():
        if v is not None and os.getenv(k) is None:
            os.environ[k] = str(v)

load_local_settings()

# --- Config: tenta usar seu settings, senão usa env vars ---
def _load_cfg():
    try:
        from src.config import settings  # se existir no seu projeto
        return {
            "endpoint": settings.SEARCH_ENDPOINT,
            "index": settings.SEARCH_INDEX,
            "api_version": settings.SEARCH_API_VERSION,
            "key": settings.SEARCH_KEY,
        }
    except Exception:
        return {
            "endpoint": os.getenv("SEARCH_ENDPOINT"),      # ex: https://xxxx.search.windows.net
            "index": os.getenv("SEARCH_INDEX"),            # ex: kb-atribuicao
            "api_version": os.getenv("SEARCH_API_VERSION", "2023-11-01"),
            "key": os.getenv("SEARCH_KEY"),
        }

cfg = _load_cfg()
missing = [k for k, v in cfg.items() if not v]
if missing:
    raise RuntimeError(f"Faltando config: {missing}. Defina env vars ou garanta src.config.settings.")

url = f"{cfg['endpoint']}/indexes/{cfg['index']}/docs/search?api-version={cfg['api_version']}"
headers = {"api-key": cfg["key"], "Content-Type": "application/json"}

# --- Paginação ---
top = 200  # seguro e rápido
skip = 0
all_files = []

while True:
    payload = {
        "search": "*",
        "queryType": "simple",
        "top": top,
        "skip": skip,
        "select": "source_file"   # só o nome do arquivo
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    batch = data.get("value", [])

    if not batch:
        break

    for doc in batch:
        sf = doc.get("source_file")
        if sf:
            all_files.append(sf)

    skip += top

# --- Resultado ---
counts = Counter(all_files)
unique_files = sorted(counts.keys())

print(f"Total docs lidos (com source_file): {len(all_files)}")
print(f"Total arquivos únicos: {len(unique_files)}\n")

for f in unique_files:
    print(f"{counts[f]:>4}  {f}")

# Dica: achar DIPES 08 rápido
print("\n--- FILTRO (DIPES 08) ---")
for f in unique_files:
    if "DIPES" in f.upper() and "08" in f:
        print(f)