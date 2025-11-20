flowchart TD
    %% Estilos
    classDef azure fill:#0072C6,stroke:#fff,stroke-width:2px,color:#fff;
    classDef python fill:#ffe05e,stroke:#333,stroke-width:2px,color:#000;
    classDef prompt fill:#ff9e5e,stroke:#333,stroke-width:1px,color:#000,stroke-dasharray: 5 5;
    classDef logic fill:#f9f9f9,stroke:#333,stroke-width:1px;

    %% Atores e Entrada
    User([👤 Usuário / Frontend]) -->|POST /search JSON| FunctionApp
    
    subgraph AzureCloud [☁️ Azure Cloud Environment]
        direction TB
        
        %% Entrypoint
        subgraph Entrypoint [📂 Root]
            FunctionApp[⚡ function_app.py]:::python
        end

        %% Orquestrador
        subgraph Orchestrator [📂 src/orchestrator]
            Router{🚦 Router.py}:::python
            Classifier[🧠 Classifier.py]:::python
            
            %% Lógica de Decisão
            Router -->|1. Analisar Intenção| Classifier
            Classifier -.->|Lê| PromptClass[📝 classifier.md]:::prompt
            Classifier -->|Retorna JSON: Modulo, Intenção, Emoção| Router
        end

        %% Módulos Especialistas (As Chains)
        subgraph Modules [📂 src/orchestrator/modules]
            direction TB
            ChainAval[🔗 avaliacao.py]:::python
            ChainClass[🔗 classificacao.py]:::python
            ChainAloc[🔗 alocacao.py]:::python
            ChainOutros[🔗 fora_escopo.py]:::python
        end

        %% Motor de Busca
        subgraph SearchCore [📂 src/search]
            RagCore[🔍 rag_core.py]:::python
            HybridSearch{Hybrid Search}:::logic
            
            RagCore -->|Executa| HybridSearch
        end

        %% Recursos Externos
        subgraph AzureServices [Azure Managed Services]
            AISearch[(🔍 Azure AI Search)]:::azure
            OpenAI_Emb[🤖 AOAI Embeddings]:::azure
            OpenAI_Chat[🤖 AOAI GPT-4o]:::azure
        end

        %% Fluxo de Roteamento
        Router -->|Case: Avaliação| ChainAval
        Router -->|Case: Classificação| ChainClass
        Router -->|Case: Alocação| ChainAloc
        Router -->|Case: Outros| ChainOutros

        %% Fluxo Interno da Chain (Exemplo: Avaliação)
        ChainAval -->|1. Busca Contexto| RagCore
        
        %% Detalhe do RAG
        HybridSearch -->|Texto| AISearch
        HybridSearch -->|Vetor| OpenAI_Emb
        OpenAI_Emb -->|Vector| AISearch
        AISearch -->|Retorna Top-K Chunks| RagCore
        RagCore -->|Retorna Lista Docs| ChainAval

        %% Geração da Resposta
        ChainAval -.->|2. Lê Prompt Específico| PromptAval[📝 avaliacao.md]:::prompt
        ChainAval -->|3. Gera Resposta c/ Contexto| OpenAI_Chat
        
        %% Caminhos dos outros módulos (simplificado visualmente)
        ChainClass -.-> PromptClassFile[📝 classificacao.md]:::prompt
        ChainClass --> OpenAI_Chat
        ChainAloc -.-> PromptAlocFile[📝 alocacao.md]:::prompt
        ChainAloc --> OpenAI_Chat

    end

    %% Retorno
    ChainAval -->|JSON Resposta| FunctionApp
    ChainClass -->|JSON Resposta| FunctionApp
    ChainAloc -->|JSON Resposta| FunctionApp
    ChainOutros -->|JSON Resposta| FunctionApp
    
    FunctionApp -->|HTTP 200 OK| User
Generate
Ctrl
↩
Awaiting input



Save and Edit Diagram
