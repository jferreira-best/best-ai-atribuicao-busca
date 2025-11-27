import os
import hashlib
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from src.orchestrator import classifier
from src.orchestrator.modules import avaliacao, classificacao, alocacao, fora_escopo

# Cache de Respostas (Mantemos em memória pois é performance, não estado crítico)
RESPONSE_CACHE = {}

# ==============================================================================
# GERENCIADOR DE ESTADO (AZURE TABLE STORAGE)
# ==============================================================================
TABLE_NAME = "ChatEstado"
CONN_STR = os.environ.get("AzureWebJobsStorage") # Usa a conexão padrão da Function

def get_table_client():
    try:
        client = TableClient.from_connection_string(conn_str=CONN_STR, table_name=TABLE_NAME)
        # Tenta criar a tabela se não existir (apenas na primeira vez)
        try:
            client.create_table()
        except ResourceExistsError:
            pass
        return client
    except Exception as e:
        print(f"Erro ao conectar no Table Storage: {e}")
        return None

def get_user_status(user_id):
    """Lê o status do usuário na tabela"""
    client = get_table_client()
    if not client: return None
    try:
        entity = client.get_entity(partition_key="chat_session", row_key=user_id)
        return entity.get("status")
    except ResourceNotFoundError:
        return None

def set_user_status(user_id, status):
    """Salva ou atualiza o status do usuário"""
    client = get_table_client()
    if not client: return
    
    entity = {
        "PartitionKey": "chat_session",
        "RowKey": user_id,
        "status": status
    }
    client.upsert_entity(entity)

def clear_user_status(user_id):
    """Limpa o status (usuário saiu do fluxo)"""
    client = get_table_client()
    if not client: return
    try:
        client.delete_entity(partition_key="chat_session", row_key=user_id)
    except ResourceNotFoundError:
        pass

# ==============================================================================
# ROTEADOR PRINCIPAL
# ==============================================================================

def route_request(query: str, full_body: dict, client_ip: str = "demo_ip"):
    
    query_lower = query.strip().lower()
    
    # LÓGICA DE ID DO USUÁRIO
    # 1. Tenta pegar o ID oficial do JSON (Produção)
    # 2. Se não tiver, usa o IP do Cliente (Desenvolvimento)
    # 3. Se tudo falhar, usa 'usuario_demo'
    user_id = full_body.get("user_id")
    if not user_id:
        user_id = f"dev_user_{client_ip.replace('.', '_')}"
        print(f"⚠️ Aviso: Usando ID baseado em IP: {user_id}")

    # 1. RECUPERA O ESTADO ATUAL DO BANCO
    current_status = get_user_status(user_id)
    print(f"🔍 Status atual do usuário {user_id}: {current_status}")

    # =========================================================================
    # 2. VERIFICAÇÃO DE INTERATIVIDADE (Fluxo em andamento?)
    # =========================================================================
    if current_status == "aguardando_trio":
        
        # Cenário A: Usuário respondeu SIM
        termos_sim = ["sim", "já", "ja", "positivo", "falei", "s", "ok", "fiz"]
        if any(t in query_lower.split() for t in termos_sim):
            print("🔄 Fluxo: Usuário confirmou. Salvando fim da sessão.")
            clear_user_status(user_id) # Limpa o banco
            return avaliacao.run_chain(query, {"intent": {"sub_intencao": "suporte_entregar_link"}})

        # Cenário B: Usuário respondeu NÃO
        termos_nao = ["não", "nao", "ainda não", "negativo", "n", "nunca"]
        if any(t in query_lower for t in termos_nao):
            print("🔄 Fluxo: Usuário negou. Salvando fim da sessão.")
            clear_user_status(user_id) # Limpa o banco
            return avaliacao.run_chain(query, {"intent": {"sub_intencao": "suporte_negar_atendimento"}})
            
        # Cenário C: Resposta nada a ver -> Limpa o estado para não travar o usuário
        clear_user_status(user_id)

    # =========================================================================
    # 3. VERIFICAÇÃO DE CACHE (Se não for interativo)
    # =========================================================================
    query_key = hashlib.md5(query_lower.encode('utf-8')).hexdigest()
    if query_key in RESPONSE_CACHE:
        print(f"⚡ Cache Hit! Retornando resposta instantânea.")
        return RESPONSE_CACHE[query_key]

    # =========================================================================
    # 4. FAST TRACK - INÍCIO DO SUPORTE
    # =========================================================================
    termos_suporte = ["chamado", "abrir chamado", "suporte", "ajuda", "não entendi", "nao entendi", "reclamar", "discordo", "preciso de ajuda"]
    
    if any(t in query_lower for t in termos_suporte):
        print(f"🚦 Iniciando Fluxo Interativo no Banco de Dados...")
        
        # SALVA NO BANCO QUE ESTAMOS ESPERANDO RESPOSTA
        set_user_status(user_id, "aguardando_trio")
        
        return avaliacao.run_chain(query, {"intent": {"sub_intencao": "suporte_perguntar_trio"}})

    # =========================================================================
    # 5. FLUXO NORMAL (Classificador LLM)
    # =========================================================================
    print(f"🧠 Chamando Classificador para: '{query}'")
    intent = classifier.classify_intent(query)
    
    modulo = intent.get("modulo", "").lower()
    
    context_data = {"intent": intent, "raw_body": full_body}

    if modulo == "avaliacao":
        result = avaliacao.run_chain(query, context_data)
    elif modulo == "classificacao":
        result = classificacao.run_chain(query, context_data)
    elif modulo == "alocacao":
        result = alocacao.run_chain(query, context_data)
    else:
        result = fora_escopo.run_chain(query, context_data)

    # Salva no Cache
    RESPONSE_CACHE[query_key] = result
    
    return result