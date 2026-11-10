# 📬 Guia de Testes da API (Postman / Insomnia)

Este documento lista todos os endpoints do **Servidor de Controle de Acesso e Monitoramento (v1)** e os exemplos práticos de payloads para testar no **Postman**, **Insomnia** ou **Thunder Client**.

---

## 🌐 Configurações Gerais

- **URL Base (Local):** `http://127.0.0.1:5000` (ou `http://localhost:5000`)
- **URL Base (Rede Local / Raspberry Pi):** `http://<IP_DA_MAQUINA>:5000`
- **Header obrigatório para rotas `POST` e `PUT`:**
  ```http
  Content-Type: application/json
  ```
- **Autenticação na API (v1):** Conforme definido em `api contratos.md`, apenas as páginas HTML do navegador exigem login; todas as rotas `/api/*` estão abertas na v1 para permitir testes diretos e integração com a Raspberry Pi e o Pandas.

---

## 1️⃣ Autenticação

### `POST /login`
Valida as credenciais do administrador.

- **Método:** `POST`
- **URL:** `http://127.0.0.1:5000/login`
- **Body (`JSON`):**
  ```json
  {
    "usuario": "admin",
    "senha": "admin"
  }
  ```
- **Respostas Esperadas:**
  - **`200 OK` (Sucesso):**
    ```json
    {
      "ok": true,
      "mensagem": "Autenticado com sucesso"
    }
    ```
  - **`401 Unauthorized` (Credenciais incorretas):**
    ```json
    {
      "ok": false,
      "erro": "Credenciais inválidas"
    }
    ```

---

### `POST /logout`
Encerra a sessão ativa do administrador.

- **Método:** `POST`
- **URL:** `http://127.0.0.1:5000/logout`
- **Resposta Esperada (`200 OK`):**
  ```json
  {
    "ok": true
  }
  ```

---

## 2️⃣ Validação de Crachá RFID (Rota da Raspberry Pi)

### `POST /api/validar`
Valida a leitura de uma tag RFID, decide o resultado com base nas regras de negócio do estúdio AAA, grava o evento no banco SQLite com o horário do servidor e retorna o resultado e a mensagem.

> 💡 **Dados iniciais já cadastrados no banco (`seed`):**
> - **Ana (`A1B2C3D4`):** Autorizada e Ativa (`acesso_sala: true`, `ativo: true`)
> - **Bruno (`B2C3D4E5`):** Autorizado e Ativo (`acesso_sala: true`, `ativo: true`)
> - **Carlos (`C3D4E5F6`):** Sem Permissão à Sala (`acesso_sala: false`, `ativo: true`)
> - **Diana (`D4E5F607`):** Colaboradora Inativa (`acesso_sala: true`, `ativo: false`)

- **Método:** `POST`
- **URL:** `http://127.0.0.1:5000/api/validar`

#### Cenário A: Colaborador Autorizado (`Ana` — Tag `A1B2C3D4`)
- **Body (`JSON`):**
  ```json
  {
    "tag_uid": "A1B2C3D4"
  }
  ```
- **Respostas Esperadas (`200 OK`):**
  - **1ª leitura no dia (Primeira Entrada):**
    ```json
    {
      "resultado": "ENTRADA",
      "mensagem": "Bem-vindo, Ana"
    }
    ```
  - **2ª leitura no dia (Saída da Sala):**
    ```json
    {
      "resultado": "SAIDA",
      "mensagem": "Até logo, Ana"
    }
    ```
  - **3ª leitura no dia (Retorno no mesmo dia):**
    ```json
    {
      "resultado": "ENTRADA",
      "mensagem": "Bem-vindo de volta, Ana"
    }
    ```

#### Cenário B: Colaborador Sem Permissão à Sala (`Carlos` — Tag `C3D4E5F6`)
- **Body (`JSON`):**
  ```json
  {
    "tag_uid": "C3D4E5F6"
  }
  ```
- **Resposta Esperada (`200 OK`):**
  ```json
  {
    "resultado": "NEGADO",
    "mensagem": "Acesso negado, Carlos"
  }
  ```

#### Cenário C: Colaborador Inativo (`Diana` — Tag `D4E5F607`)
- **Body (`JSON`):**
  ```json
  {
    "tag_uid": "D4E5F607"
  }
  ```
- **Resposta Esperada (`200 OK`):**
  ```json
  {
    "resultado": "NEGADO",
    "mensagem": "Acesso negado, Diana"
  }
  ```

#### Cenário D: Tag Não Cadastrada / Desconhecida (`INVASAO`)
- **Body (`JSON`):**
  ```json
  {
    "tag_uid": "9999FFFF"
  }
  ```
- **Resposta Esperada (`200 OK`):**
  ```json
  {
    "resultado": "INVASAO",
    "mensagem": "Alerta de invasão: Tag não cadastrada"
  }
  ```

---

## 3️⃣ Gerenciamento de Colaboradores (CRUD + Cache da Pi)

### `GET /api/colaboradores`
Retorna todos os colaboradores cadastrados com suas permissões e o estado atual no dia (`na_sala`, `entrou_hoje`, `tempo_hoje_segundos`).
> A Raspberry Pi chama esta rota ao ligar e depois **a cada 3 minutos** para atualizar seu `cache.json`.

- **Método:** `GET`
- **URL:** `http://127.0.0.1:5000/api/colaboradores`
- **Resposta Esperada (`200 OK`):**
  ```json
  [
    {
      "id": 1,
      "nome": "Ana",
      "matricula": "01",
      "tag_uid": "A1B2C3D4",
      "cargo": "Character Artist",
      "acesso_sala": true,
      "ativo": true,
      "na_sala": true,
      "entrou_hoje": true,
      "tempo_hoje_segundos": 120
    }
  ]
  ```

---

### `POST /api/colaboradores`
Cadastra um novo colaborador no sistema.

- **Método:** `POST`
- **URL:** `http://127.0.0.1:5000/api/colaboradores`
- **Body (`JSON`):**
  ```json
  {
    "nome": "Eduardo",
    "matricula": "05",
    "tag_uid": "E5F60718",
    "cargo": "Game Director",
    "acesso_sala": true,
    "ativo": true
  }
  ```
- **Respostas Esperadas:**
  - **`200 OK`:** Retorna o objeto do colaborador criado com seu novo `id`.
  - **`400 Bad Request`:** Caso falte algum campo obrigatório ou caso `matricula` / `tag_uid` já estejam cadastrados.

---

### `PUT /api/colaboradores/<id>`
Atualiza os dados, a tag RFID ou as permissões (`acesso_sala`, `ativo`) de um colaborador existente.

- **Método:** `PUT`
- **URL (Exemplo para `id = 5`):** `http://127.0.0.1:5000/api/colaboradores/5`
- **Body (`JSON`):**
  ```json
  {
    "nome": "Eduardo Oliveira",
    "matricula": "05",
    "tag_uid": "E5F60718",
    "cargo": "Game Director",
    "acesso_sala": false,
    "ativo": true
  }
  ```
- **Respostas Esperadas:**
  - **`200 OK`:** Retorna o objeto atualizado.
  - **`404 Not Found`:** Caso o `id` informado não exista.
  - **`400 Bad Request`:** Caso a nova `matricula` ou `tag_uid` conflite com outro colaborador.

---

### `DELETE /api/colaboradores/<id>`
Remove um colaborador do banco de dados pelo `id`.

- **Método:** `DELETE`
- **URL (Exemplo para `id = 5`):** `http://127.0.0.1:5000/api/colaboradores/5`
- **Respostas Esperadas:**
  - **`200 OK`:**
    ```json
    {
      "ok": true
    }
    ```
  - **`404 Not Found`:**
    ```json
    {
      "erro": "Colaborador não encontrado"
    }
    ```

---

## 4️⃣ Consulta de Eventos e Exportação CSV

### `GET /api/eventos`
Retorna os eventos registrados ordenados do mais recente para o mais antigo (usado pelo painel de monitoramento a cada 2 segundos).

- **Método:** `GET`
- **Variações de URL para testar:**
  1. **Eventos de hoje (Padrão):**
     `http://127.0.0.1:5000/api/eventos`
  2. **Filtrar por data específica (`YYYY-MM-DD`):**
     `http://127.0.0.1:5000/api/eventos?data=2026-10-27`
  3. **Listar todo o histórico do banco:**
     `http://127.0.0.1:5000/api/eventos?todos=true`
- **Resposta Esperada (`200 OK`):**
  ```json
  [
    {
      "id": 1,
      "data_hora": "2026-10-27 21:36:10",
      "tag_uid": "A1B2C3D4",
      "nome": "Ana",
      "resultado": "ENTRADA"
    }
  ]
  ```

---

### `GET /api/eventos.csv`
Exporta todo o histórico de eventos em formato CSV (rota dedicada para análise de dados com Pandas).

- **Método:** `GET`
- **URL:** `http://127.0.0.1:5000/api/eventos.csv`
- **Resposta Esperada (`200 OK` — `text/csv`):**
  ```csv
  id,data_hora,tag_uid,nome,resultado
  1,2026-10-27 21:36:10,A1B2C3D4,Ana,ENTRADA
  ```
