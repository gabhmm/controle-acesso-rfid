# 📄 PRD (Product Requirements Document) — Controle de Acesso e Monitoramento v1 (Server & Web Client)

## 1. Visão Geral do Produto
- **Nome da Demanda:** `controle-acesso-v1`
- **Contexto de Negócio:** Um estúdio de desenvolvimento de jogos fechou um contrato de *outsourcing* com uma *publisher* AAA para criar o design de personagens confidenciais sob rigoroso NDA (*Non-Disclosure Agreement*). Para proteger os ativos do projeto contra vazamentos, foi criada uma sala física isolada e de acesso restrito.
- **Objetivo Principal (O Quê):** Desenvolver a **Aplicação Conectada (Servidor Backend em Flask + SQLite)** e o **Cliente Web (Sistema de Gerenciamento de Acessos + Página de Monitoramento em Tempo Real)**, atuando como o hub centralizador ("versão única da verdade") para validação de acessos, gestão de colaboradores/permissões, exibição de alertas para a empresa de segurança privada e exportação estruturada de logs.
- **Justificativa de Negócio (Por Quê):** Garantir conformidade com o NDA da publisher AAA, controlando e auditando em tempo real quem entra, quem sai, quem tenta acessar sem permissão (`NEGADO`) e tentativas de invasão com crachás desconhecidos (`INVASAO`).

---

## 2. Personas e Atores

```mermaid
graph LR
    Pi["🍓 Raspberry Pi (Externa ao Escopo)"] -->|POST /api/validar| Server["🖥️ Servidor Flask + SQLite (server/)"]
    Pi -->|GET /api/colaboradores| Server
    Admin["🛡️ Gestor de Acessos"] -->|Login + CRUD Colaboradores/Tags/Logs| WebClient["🌐 Cliente Web (client/)"]
    Seguranca["🚨 Segurança Privada"] -->|Monitoramento em Tempo Real (Polling 2s)| WebClient
    WebClient -->|Consome API JSON| Server
    Export["📄 Exportação CSV"] -->|GET /api/eventos.csv| Server
```

1. **🛡️ Gestor de Acessos (Administrador):** Responsável por autenticar no sistema web, cadastrar/editar/excluir colaboradores, associar tags RFID, definir permissões de acesso à sala do projeto AAA e consultar registros.
2. **🚨 Operador de Segurança Privada:** Acompanha a página de monitoramento em tempo real (atualizada a cada 2 segundos) para visualizar quem está atualmente dentro da sala, últimas entradas/saídas e alertas imediatos de acesso negado ou invasão.
3. **🍓 Sistema Embarcado Raspberry Pi (Consumidor Externo da API):** Dispositivo físico (desenvolvido separadamente) que consome `GET /api/colaboradores` ao ligar e periodicamente a cada 3 minutos para atualizar seu cache local (`cache.json`), e envia `POST /api/validar` com o `tag_uid` lido.

---

## 3. Requisitos Funcionais (RF)

### Módulo 1: Servidor Backend & API (`server/`)
- **RF01 — Autenticação (`POST /login`):**
  - Validar credenciais (`usuario` e `senha`) do administrador.
  - Retornar `200 OK` em caso de sucesso ou `401 Unauthorized` em caso de falha.
- **RF02 — Gerenciamento de Colaboradores (`GET`, `POST`, `PUT`, `DELETE /api/colaboradores`):**
  - Cada colaborador deve possuir:
    - `id` (identificador único)
    - `nome` (nome completo)
    - `matricula` (identificação na empresa)
    - `tag_uid` (código da tag RFID do crachá)
    - `cargo` (função no estúdio, ex: `Artist`, `Developer`)
    - `acesso_sala` (`bool`: se possui autorização para entrar na sala do projeto AAA)
    - `ativo` (`bool`: status ativo/inativo na empresa)
  - `GET /api/colaboradores`: Retorna a lista completa e atualizada de colaboradores em JSON (`id`, `nome`, `matricula`, `tag_uid`, `cargo`, `acesso_sala`, `ativo`), enriquecida dinamicamente com o estado do dia (`na_sala`: bool, `entrou_hoje`: bool, `tempo_hoje_segundos`: int). Usada pelo Front-end e requisitada pela Raspberry Pi na inicialização (boot) e a cada **3 minutos** para sincronizar o estado local (`cache.json`).
  - `POST /api/colaboradores`: Cadastra novo colaborador.
  - `PUT /api/colaboradores/<id>`: Atualiza dados, tag RFID, permissão `acesso_sala` ou status `ativo`.
  - `DELETE /api/colaboradores/<id>`: Remove um colaborador.
- **RF03 — Validação e Registro de Acesso (`POST /api/validar`):**
  - Recebe `{ "tag_uid": "..." }`.
  - Avalia as regras de negócio (RN01 a RN04), grava o evento no banco SQLite com a data/hora do servidor (`YYYY-MM-DD HH:MM:SS`) e retorna `{ "resultado": "...", "mensagem": "..." }`.
- **RF04 — Listagem de Eventos (`GET /api/eventos`):**
  - Retorna os eventos registrados no dia atual por padrão (ou filtrados por `?data=YYYY-MM-DD` / `?todos=true`), ordenados do mais recente para o mais antigo (`id`, `data_hora`, `tag_uid`, `nome`, `resultado`).
- **RF05 — Exportação de Logs em CSV (`GET /api/eventos.csv`):**
  -Disponibiliza o download/leitura de todos os eventos registrados em formato CSV (`id,data_hora,tag_uid,nome,resultado`).

### Módulo 2: Cliente Web — Gerenciamento e Monitoramento (`client/` ou servido via `server/`)
- **RF06 — Tela de Login:**
  - Formulário simples de usuário e senha que autentica via `POST /login` antes de liberar as telas administrativas.
- **RF07 — Tela de Gerenciamento de Colaboradores:**
  - Listar todos os colaboradores cadastrados com seus respectivos status (`acesso_sala`, `ativo`, `tag_uid`, `matricula`, `cargo`).
  - Cadastrar novos colaboradores e editar ou excluir existentes.
  - Permitir alterar rapidamente a tag RFID, a permissão de acesso à sala e o status ativo/inativo.
- **RF08 — Página de Monitoramento em Tempo Real (Segurança Privada):**
  - Atualização automática via *polling* a cada **2 segundos** em `GET /api/eventos`.
  - Exibir claramente em painéis/seções distintas:
    1. **Colaboradores atualmente dentro da sala** (cujo último evento do dia é `ENTRADA`).
    2. **Últimas entradas autorizadas** (`resultado == "ENTRADA"`).
    3. **Últimas saídas registradas** (`resultado == "SAIDA"`).
    4. **Tentativas de acesso de colaboradores não autorizados** (`resultado == "NEGADO"`).
    5. **Tentativas de invasão com tags desconhecidas** (`resultado == "INVASAO"`).
    6. **Alertas recentes** (destaque visual para eventos `NEGADO` e, com severidade máxima, `INVASAO`).

---

## 4. Regras de Negócio (RN) — Especificação Oficial do Estúdio

- **RN01 — Tag Não Cadastrada (`INVASAO`):**
  - Se o `tag_uid` enviado em `POST /api/validar` **não estiver cadastrado** no banco de dados:
    - `resultado`: `"INVASAO"`
    - `nome` gravado no evento: `"Desconhecido"` (ou similar identificando tag não cadastrada)
    - `mensagem`: `"Alerta de invasão: Tag não cadastrada"`
- **RN02 — Colaborador Sem Permissão ou Inativo (`NEGADO`):**
  - Se o `tag_uid` pertencer a um colaborador cadastrado, mas `acesso_sala == false` ou `ativo == false`:
    - `resultado`: `"NEGADO"`
    - `nome` gravado no evento: `{nome do colaborador}`
    - `mensagem`: `"Acesso negado, {nome}"`
- **RN03 — Colaborador Autorizado (`ENTRADA` vs `SAIDA` e Mensagens de Boas-Vindas):**
  - Se o colaborador estiver cadastrado, com `ativo == true` e `acesso_sala == true`:
    - Verifica-se o histórico de eventos (`ENTRADA` / `SAIDA`) desse colaborador **no dia atual**:
    - **Caso 1 (Primeira entrada no dia):** Ainda não entrou na sala hoje.
      - `resultado`: `"ENTRADA"`
      - `mensagem`: `"Bem-vindo, {nome}"`
    - **Caso 2 (Saída da sala):** O último evento dele hoje foi `"ENTRADA"`.
      - `resultado`: `"SAIDA"`
      - `mensagem`: `"Até logo, {nome}"`
    - **Caso 3 (Retorno no mesmo dia):** O último evento dele hoje foi `"SAIDA"` (já entrou anteriormente no mesmo dia).
      - `resultado`: `"ENTRADA"`
      - `mensagem`: `"Bem-vindo de volta, {nome}"`
- **RN04 — Cálculo de "Dentro da Sala":**
  - Um colaborador é considerado "Dentro da Sala" se, e somente se, o seu **último evento registrado no dia atual** possuir `resultado == "ENTRADA"`.
- **RN05 — Controle de Acesso às Rotas (Contrato v1):**
  - Apenas as telas do Front-end exigem login; as rotas `/api/*` ficam abertas na v1 conforme o contrato de API.

---

## 5. Requisitos Não-Funcionais (RNF)

- **RNF01 — Python 3.12+ & Padrões Mestre Jedi:** Uso obrigatório de `type hints` estritos e `dataclasses` para modelagem de entidades e DTOs.
- **RNF02 — Banco de Dados Relacional Leve:** Persistência centralizada em `SQLite` (`sqlite3`) garantindo uma versão única da verdade.
- **RNF03 — Fidelidade ao Contrato de API:** Respeitar integralmente os endpoints, métodos HTTP, formatos de data (`YYYY-MM-DD HH:MM:SS`) e chaves JSON definidos em `api contratos.md`.

---

## 6. Fora de Escopo (Fará parte de outras entregas da equipe)
- **Hardware / Código embarcado da Raspberry Pi** (leitura física RC522, GPIO, LEDs, buzzer e cache local na Pi serão feitos separadamente).
- **Análise de Dados com Pandas / Jupyter Notebook** (será feito separadamente consumindo o endpoint `/api/eventos.csv` ou o banco SQLite).
- **Documentação acadêmica em PDF** (orçamento, fotos reais do MVP, projetos similares, etc.).

---

## 7. Critérios de Aceite
- [ ] Banco SQLite inicializado automaticamente com tabelas `colaboradores` e `eventos` (e credencial admin padrão).
- [ ] Endpoints `POST /login`, `GET/POST /api/colaboradores`, `PUT/DELETE /api/colaboradores/<id>`, `POST /api/validar`, `GET /api/eventos` e `GET /api/eventos.csv` operando conforme `api contratos.md`.
- [ ] Regras de mensagem e classificação (`Bem-vindo, {nome}`, `Bem-vindo de volta, {nome}`, `SAIDA`, `NEGADO` para sem permissão, `INVASAO` para tag desconhecida) validadas por testes automatizados.
- [ ] Interface Web responsiva com Login, CRUD completo de colaboradores e Página de Monitoramento em Tempo Real (polling 2s) exibindo presentes na sala, entradas, saídas, negados, invasões e alertas.
