import sys
import os
# --- BOOTSTRAP DE BIBLIOTECAS (CRUCIAL) ---
# Adiciona a pasta _libs/site-packages ao caminho do Python
root_path = os.path.dirname(os.path.abspath(__file__))
libs_path = os.path.join(root_path, '_libs', 'site-packages')
sys.path.insert(0, libs_path) # Prioridade máxima
sys.path.append(root_path)
# ------------------------------------------
import azure.functions as func
import logging
import json

# --- CONFIGURACAO DE CAMINHO ---
root_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(root_path)
# -------------------------------

app = func.FunctionApp()

@app.function_name(name="search_atribuicao")
@app.route(
    route="search_atribuicao",
    auth_level=func.AuthLevel.ANONYMOUS,
    methods=["POST"],
)
def http_search_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Recebendo requisicao.")

    try:
        # Tenta importar
        from src.orchestrator import router

        # Se importar com sucesso, segue o fluxo normal...
        body = req.get_json()
        query = body.get("query")
        
        if not query:
            return func.HttpResponse("JSON invalido: 'query' obrigatorio", status_code=400)

        client_ip = req.headers.get("x-forwarded-for") or "127.0.0.1"
        client_ip = client_ip.split(",")[0].split(":")[0]

        result = router.route_request(query, body, client_ip)

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status_code=200,
        )

    except ImportError as ie:
        # === O RAIO-X: LISTAR ARQUIVOS NO RETORNO DO ERRO ===
        try:
            lista_raiz = os.listdir(root_path)
            debug_info = f"1. Pasta Raiz ({root_path}): {lista_raiz}\n"
            
            if 'src' in lista_raiz:
                caminho_src = os.path.join(root_path, 'src')
                lista_src = os.listdir(caminho_src)
                debug_info += f"2. Dentro da pasta 'src': {lista_src}"
            else:
                debug_info += "2. ERRO: A pasta 'src' NAO existe na raiz!"
                
        except Exception as e_debug:
            debug_info = f"Erro ao listar arquivos: {str(e_debug)}"
        # ====================================================

        return func.HttpResponse(
            f"ERRO DE IMPORTACAO:\n{str(ie)}\n\n--- DIAGNOSTICO DE ARQUIVOS ---\n{debug_info}",
            status_code=500,
        )
    except Exception as e:
        return func.HttpResponse(f"Erro critico: {str(e)}", status_code=500)