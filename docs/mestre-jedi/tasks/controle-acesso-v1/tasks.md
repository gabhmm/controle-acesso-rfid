# ✅ Tasks (Plano de Execução) — Controle de Acesso e Monitoramento v1

Este plano segue rigorosamente o trinômio `PRD` -> `TechSpec` -> `Tasks` do **Mestre Jedi**. Nenhuma etapa deve ser pulada.

---

## 📦 Fase 1: Modelagem de Domínio e Camada de Persistência (`server/`)
- [x] **Task 1.1 — Configuração (`server/config.py` e `server/__init__.py`):**
  - Definir constantes de configuração com *type hints* (`DB_PATH`, `SECRET_KEY`, `ADMIN_USER = "admin"`, `ADMIN_PASS = "admin"`).
- [x] **Task 1.2 — Entidades e Dataclasses (`server/models.py`):**
  - Implementar `@dataclass(slots=True)` para `Colaborador` (incluindo `na_sala`, `entrou_hoje`, `tempo_hoje_segundos`), `Evento` e `RespostaValidacao`, além do tipo literal `ResultadoEvento`.
- [x] **Task 1.3 — Repositório SQLite3 (`server/database.py`):**
  - Implementar inicialização automática do esquema (`colaboradores` e `eventos` + índices).
  - Implementar seed opcional de dados iniciais (se a tabela `colaboradores` estiver vazia, cadastrar colaboradores de exemplo do estúdio AAA para facilitar testes imediatos).
  - Implementar métodos CRUD parametrizados para `colaboradores` e consultas/inserções para `eventos`.

---

## ⚙️ Fase 2: Regras de Negócio e Serviços (`server/services.py`)
- [x] **Task 2.1 — Cálculo de Presença e Tempo Diário:**
  - Implementar função que processa os eventos do dia de cada colaborador para calcular:
    - `na_sala` (`bool`: último evento `ENTRADA`/`SAIDA` do dia é `ENTRADA`).
    - `entrou_hoje` (`bool`: possui ao menos uma `ENTRADA` no dia).
    - `tempo_hoje_segundos` (`int`: soma dos intervalos `[ENTRADA -> SAIDA]` fechados no dia + intervalo `[ENTRADA -> agora]` caso ainda esteja dentro da sala).
- [x] **Task 2.2 — Máquina de Estados de Validação (`validar_acesso`):**
  - Normalizar `tag_uid` (`strip().upper()`).
  - Aplicar **RN01**: Tag não encontrada no banco → gravar evento `INVASAO` (`nome="Desconhecido"`) e retornar `"Alerta de invasão: Tag não cadastrada"`.
  - Aplicar **RN02**: Colaborador encontrado, porém `ativo == False` ou `acesso_sala == False` → gravar evento `NEGADO` e retornar `"Acesso negado, {nome}"`.
  - Aplicar **RN03**: Colaborador autorizado (`ativo == True` e `acesso_sala == True`):
    - Se `not entrou_hoje` → gravar `ENTRADA`, retornar `"Bem-vindo, {nome}"`.
    - Se `na_sala` → gravar `SAIDA`, retornar `"Até logo, {nome}"`.
    - Se `entrou_hoje and not na_sala` → gravar `ENTRADA`, retornar `"Bem-vindo de volta, {nome}"`.

---

## 🖥️ Fase 3: Rotas da API REST e Servidor Flask (`server/app.py`)
- [x] **Task 3.1 — Autenticação e Rotas de Páginas:**
  - Implementar `POST /login` (`200` ou `401`) e `POST /logout` com sessão Flask.
  - Implementar rotas das telas Front-end (`GET /`, `GET /login`, `GET /colaboradores`, `GET /monitor`) protegidas por verificação de login.
- [x] **Task 3.2 — Endpoints de Colaboradores (`/api/colaboradores`):**
  - Implementar `GET /api/colaboradores` (retornando lista enriquecida com `na_sala`, `entrou_hoje`, `tempo_hoje_segundos` e header `Cache-Control: no-store`).
  - Implementar `POST /api/colaboradores`, `PUT /api/colaboradores/<id>` e `DELETE /api/colaboradores/<id>` com tratamento de erros (`400` para duplicidade de matrícula/tag, `404` quando não encontrado).
- [x] **Task 3.3 — Endpoints de Validação, Eventos e CSV:**
  - Implementar `POST /api/validar`.
  - Implementar `GET /api/eventos` (eventos do dia por padrão, suportando `?data=YYYY-MM-DD` e `?todos=true`, mais recentes primeiro).
  - Implementar `GET /api/eventos.csv` exportando todos os eventos no formato `id,data_hora,tag_uid,nome,resultado`.

---

## 🌐 Fase 4: Cliente Web — Gerenciamento e Monitoramento (`client/`)
- [x] **Task 4.1 — Identidade Visual & Utilitários (`client/static/`):**
  - Criar `client/static/css/styles.css` com design moderno Dark Mode (Centro de Controle de Segurança AAA), badges de status (`ENTRADA`, `SAIDA`, `NEGADO`, `INVASAO`), animações de alerta e layout responsivo.
  - Criar `client/static/js/api.js` centralizando chamadas `fetch()` e formatação de tempo (`HH:MM:SS`).
- [x] **Task 4.2 — Tela de Login (`client/templates/login.html`):**
  - Formulário de login integrado ao `POST /login` com feedback visual de erro e redirecionamento automático.
- [x] **Task 4.3 — Tela de Gestão de Colaboradores (`client/templates/colaboradores.html` + `colaboradores.js`):**
  - Tabela completa exibindo: Nome, Matrícula, Cargo, Tag RFID, Permissão Sala (`acesso_sala`), Status (`ativo`), Estado Atual (`Na Sala` / `Fora`) e Tempo Acumulado Hoje.
  - Modal/Formulário para Cadastrar e Editar colaborador (incluindo edição de Tag RFID e toggles rápidos de `acesso_sala` e `ativo`) + botão Excluir.
- [x] **Task 4.4 — Página de Monitoramento em Tempo Real (`client/templates/monitor.html` + `monitor.js`):**
  - Implementar *polling* automático a cada **2 segundos** (`GET /api/eventos` + `GET /api/colaboradores`).
  - Renderizar as 6 visões exigidas para a empresa de segurança privada:
    1. **Colaboradores Atualmente Dentro da Sala** (com contador e tempo de permanência ao vivo).
    2. **Alertas Recentes de Segurança** (destaque para `INVASAO` e `NEGADO`).
    3. **Últimas Entradas Autorizadas** (`ENTRADA`).
    4. **Últimas Saídas Registradas** (`SAIDA`).
    5. **Tentativas de Acesso Não Autorizado** (`NEGADO`).
    6. **Tentativas de Invasão com Tags Desconhecidas** (`INVASAO`).
  - Incluir barra de **Simulador Rápido de Leitura RFID** (`POST /api/validar`) e link de download rápido para `/api/eventos.csv`.

---

## 🧪 Fase 5: Testes Automatizados e Validação Final (`tests/`)
- [x] **Task 5.1 — Suíte de Testes Automatizados (`tests/test_server.py`):**
  - Testar `POST /login` (sucesso e falha).
  - Testar ciclo CRUD completo em `/api/colaboradores` e presença dos campos `na_sala`, `entrou_hoje`, `tempo_hoje_segundos`.
  - Testar todos os cenários de `POST /api/validar` (`INVASAO`, `NEGADO` por permissão, `NEGADO` por inativo, 1ª `ENTRADA`, `SAIDA`, 2ª `ENTRADA` com `"Bem-vindo de volta"`).
  - Testar `GET /api/eventos` e `GET /api/eventos.csv`.
- [x] **Task 5.2 — Execução e Verificação:**
  - Rodar a suíte de testes no `.venv` local e garantir 100% de aprovação.
  - Atualizar o `README.md` na raiz com instruções claras de como iniciar o servidor e acessar as telas.
