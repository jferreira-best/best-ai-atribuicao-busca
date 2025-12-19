# get_resumo_professor_atribuicao_retry.py
import argparse
import json
import sys
import time
import requests

URL = "https://see-d-atribuicao-api.azurewebsites.net/api/Atribuicao/GetResumoProfessorAtribuicaoAsync"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codigo-diretoria", type=int, required=True)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=2.0, help="base do backoff em segundos")
    args = ap.parse_args()

    headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.8"}
    params = {"codigoDiretoria": args.codigo_diretoria}

    last_err = None
    for attempt in range(1, args.retries + 1):
        try:
            r = requests.get(URL, params=params, headers=headers, timeout=args.timeout)

            if r.ok:
                try:
                    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
                except Exception:
                    print(r.text)
                return

            # Se veio JSON de erro, imprime
            try:
                err = r.json()
                last_err = err
                msg = err.get("message") or r.text
            except Exception:
                msg = r.text

            print(f"[tentativa {attempt}/{args.retries}] HTTP {r.status_code}: {msg}", file=sys.stderr)

            # Se for erro de DB indisponível, vale retry
            if "Database" in msg and "is not currently available" in msg and attempt < args.retries:
                time.sleep(args.sleep * attempt)  # backoff simples
                continue

            sys.exit(1)

        except requests.RequestException as e:
            last_err = str(e)
            print(f"[tentativa {attempt}/{args.retries}] Erro de rede: {e}", file=sys.stderr)
            if attempt < args.retries:
                time.sleep(args.sleep * attempt)
                continue
            sys.exit(1)

    print(f"Falhou após {args.retries} tentativas. Último erro: {last_err}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
