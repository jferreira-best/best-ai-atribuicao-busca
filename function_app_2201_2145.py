import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import azure.functions as func
import logging
import json

app = func.FunctionApp()


@app.function_name(name="search_atribuicao")
@app.route(
    route="search_atribuicao",
    auth_level=func.AuthLevel.ANONYMOUS,
    methods=["POST"],
)
def http_search_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Recebendo requisição no Orquestrador V2 (Fast Track).")

    try:
        # IMPORTA O ROUTER AQUI DENTRO
        from src.orchestrator import router

        body = req.get_json()

        query = body.get("query")
        if not query:
            return func.HttpResponse(
                "JSON inválido: 'query' é obrigatório",
                status_code=400,
            )

        client_ip = req.headers.get("x-forwarded-for")
        if not client_ip:
            client_ip = "127.0.0.1"
        else:
            client_ip = client_ip.split(",")[0].split(":")[0]

        result = router.route_request(query, body, client_ip)

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status_code=200,
        )

    except Exception as e:
        logging.exception(f"Erro crítico: {e}")
        return func.HttpResponse(
            f"Erro interno: {str(e)}",
            status_code=500,
        )
