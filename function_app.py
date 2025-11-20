import azure.functions as func
import logging
import json
from src.orchestrator import router

app = func.FunctionApp()

@app.route(route="search", auth_level=func.AuthLevel.ANONYMOUS, methods=['POST'])
def http_search_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Recebendo requisição no Orquestrador de Agentes Docente.')

    try:
        body = req.get_json()
        query = body.get("query")
        
        if not query:
            return func.HttpResponse("Por favor, envie um JSON com {'query': 'sua pergunta'}", status_code=400)

        # Chama o Router (O Maestro)
        result = router.route_request(query, body)

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.exception(f"Erro crítico: {e}")
        return func.HttpResponse(f"Erro interno: {str(e)}", status_code=500)