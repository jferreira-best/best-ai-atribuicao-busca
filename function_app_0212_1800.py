import azure.functions as func
import logging
import json
from src.orchestrator import router

app = func.FunctionApp()


@app.function_name(name="search_atribuicao")
@app.route(route="search_atribuicao", auth_level=func.AuthLevel.ANONYMOUS, methods=['POST'])
def http_search_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Recebendo requisição no Orquestrador de Agentes Docente.')

    try:
        body = req.get_json()
        query = body.get("query")
        
        if not query:
            return func.HttpResponse("JSON inválido", status_code=400)

        # --- CAPTURA DE IP (HACK PARA DEV) ---
        # Tenta pegar o IP real (se estiver na nuvem) ou local
        client_ip = req.headers.get("x-forwarded-for")
        if not client_ip:
            client_ip = "127.0.0.1" # Fallback local
        else:
            client_ip = client_ip.split(',')[0].split(':')[0] # Limpa o IP
        # -------------------------------------

        # Passamos o IP como terceiro argumento
        result = router.route_request(query, body, client_ip)

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.exception(f"Erro crítico: {e}")
        return func.HttpResponse(f"Erro interno: {str(e)}", status_code=500)