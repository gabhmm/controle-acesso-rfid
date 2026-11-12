# ✅ Tasks (Plano de Execução) — Controle de Acesso Distribuído v2

Este plano segue o trinômio **PRD $\rightarrow$ TechSpec $\rightarrow$ Tasks** do Mestre Jedi. Nenhuma etapa deve ser pulada e cada tarefa deve ser validada com testes.

---

## 📦 Fase 1: Infraestrutura e Dependências
- [x] **Task 1.1 — Atualização do `requirements.txt`:**
  - Incluir `fastapi`, `uvicorn[standard]`, `pydantic`, `redis`, `pika`, `python-multipart`, mantendo retrocompatibilidade com bibliotecas de hardware (`spidev`, `mfrc522` como opcionais/condicionais).
- [x] **Task 1.2 — Orquestração Local com `docker-compose.yml`:**
  - Configurar serviço do **Redis** (porta `6379`).
  - Configurar serviço do **RabbitMQ** com painel de gerenciamento (portas `5672` e `15672`).

---

## 🔴 Fase 2: Cache Distribuído (Redis) e Mensageria (RabbitMQ)
- [x] **Task 2.1 — Cliente e Estratégia de Cache Redis (`server/redis_client.py`):**
  - Implementar conexão resiliente ao Redis com reconexão automática e modo degradado (*graceful fallback*) caso o Redis esteja indisponível.
  - Implementar funções de cache-aside para tags: `obter_tag_cache(tag_uid)`, `salvar_tag_cache(tag_uid, dados, ttl=300)`, `invalidar_tag_cache(tag_uid)`.
  - Implementar cache do dashboard: `obter_dashboard_cache()`, `salvar_dashboard_cache(dados, ttl=10)`.
- [x] **Task 2.2 — Produtor de Mensageria RabbitMQ (`server/rabbit_producer.py`):**
  - Implementar conexão com RabbitMQ e declaração da fila durável `eventos_acesso`.
  - Implementar função de publicação assíncrona não bloqueante `publicar_evento(evento_dict)`.
- [x] **Task 2.3 — Worker Consumidor Assíncrono (`worker/consumer.py`):**
  - Implementar script autônomo consumidor que escuta a fila `eventos_acesso`.
  - Ao receber a mensagem, realizar o `INSERT` no SQLite via `DatabaseRepository` e enviar o `basic_ack`.
  - Tratar exceções para evitar perda de mensagens.

---

## ⚡ Fase 3: Servidor API REST com FastAPI (`server/`)
- [x] **Task 3.1 — Modelos Pydantic e Dataclasses (`server/models.py`):**
  - Atualizar/definir esquemas Pydantic para validação de entrada e saída: `TagValidarRequest`, `ValidacaoResponse`, `ColaboradorCreate`, `ColaboradorUpdate`, `ColaboradorResponse`, `DashboardResponse`.
- [x] **Task 3.2 — Migração do Servidor para FastAPI (`server/app.py`):**
  - Configurar aplicação FastAPI com rotas REST completas.
  - Migrar `POST /api/validar` para o novo fluxo:
    1. Consulta Cache Redis (Hit $\rightarrow$ dados imediatos; Miss $\rightarrow$ busca no SQLite e grava no Redis).
    2. Aplica regras de negócio (`ENTRADA`, `SAIDA`, `NEGADO`, `INVASAO`).
    3. Publica evento no RabbitMQ.
    4. Retorna resposta JSON imediatamente.
  - Implementar `GET /api/dashboard/10min` consultando o Redis (ou agregando do banco em caso de miss).
  - Manter endpoints de CRUD de colaboradores e rotas estáticas para servir o front-end HTML/CSS/JS.

---

## 📟 Fase 4: Módulo de Hardware na Raspberry Pi (`hardware/`)
- [x] **Task 4.1 — Driver e Controlador de Hardware (`hardware/rfid_reader.py`):**
  - Implementar classe `HardwareController` com detecção de ambiente:
    - Se estiver na Raspberry Pi: inicializar GPIO (LED Verde no pino 17, LED Vermelho no pino 27, Buzzer no pino 22) e leitor RC522 via SPI.
    - Se estiver em PC de desenvolvimento: ativar `MockHardwareController` que exibe logs coloridos no console e permite simulação interativa via terminal.
  - Implementar métodos de sinalização:
    - `acesso_liberado(nome)`: acende LED verde por 2s + bipe curto no buzzer.
    - `acesso_negado(motivo)`: pisca LED vermelho por 2s + 3 bipes rápidos no buzzer.
  - Implementar loop contínuo de leitura de cartão chamando a API `POST /api/validar`.

---

## 🌐 Fase 5: Front-end Web, Testes e Documentação
- [x] **Task 5.1 — Atualização do Front-end Web (`client/static/js/monitor.js`):**
  - Atualizar o painel de monitoramento para consumir o novo endpoint `/api/dashboard/10min` em cache.
  - Exibir visualmente os tempos de resposta sub-milissegundos viabilizados pelo Redis.
- [x] **Task 5.2 — Suíte de Testes Automatizados (`tests/`):**
  - Testes unitários com mocks para Redis e RabbitMQ.
  - Teste de ponta a ponta do fluxo de validação e persistência do worker.
- [x] **Task 5.3 — Documentação no `README.md`:**
  - Guia passo a passo de como subir o Redis/RabbitMQ via Docker.
  - Instruções de pinout e execução do script na Raspberry Pi.
  - Guia de execução e teste no computador de desenvolvimento.
