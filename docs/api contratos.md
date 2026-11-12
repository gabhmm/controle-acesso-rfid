# Contrato de API — v1 (mínimo funcionando)

`resultado`: `ENTRADA` · `SAIDA` · `NEGADO` · `INVASAO`

Todas as rotas usam JSON. Só as telas do front exigem login; a API fica aberta na v1.

## Resumo

| Origem | Rota | Função |
| --- | --- | --- |
| Pi | `POST /api/validar` | Valida e registra cada leitura |
| Pi | `GET /api/colaboradores` | Cache para modo offline |
| Front | `POST /login` | Login |
| Front | `GET` · `POST /api/colaboradores` | Listar · cadastrar |
| Front | `PUT` · `DELETE /api/colaboradores/<id>` | Editar · excluir |
| Front | `GET /api/eventos` | Logs e monitoramento (polling 2 s) |
| Pandas | `GET /api/eventos.csv` | Exporta logs |


---

## Raspberry → Servidor

### `POST /api/validar`
- `tag_uid`: código lido do crachá.

O servidor decide o resultado, grava o evento com o horário dele e devolve a mensagem.
```json
// body
{ "tag_uid": "A1B2C3D4" }
// 200
{ "resultado": "ENTRADA", "mensagem": "Bem-vindo, Ana" }
```
Sem resposta em 2 s → Pi decide pela lista em cache e grava o evento num arquivo local.

### `GET /api/colaboradores`
Mesma rota do front. A Pi chama ao ligar e depois a cada 3 minutos para atualizar seu estado local (`cache.json`), incluindo se o colaborador está atualmente na sala (`na_sala`), se já entrou hoje (`entrou_hoje`) e o tempo acumulado no dia (`tempo_hoje_segundos`).

---

## Front → Servidor

### `POST /login`
- `usuario` / `senha`: credenciais do administrador.
```json
// body
{ "usuario": "admin", "senha": "admin" }
// 200 | 401
```

### `GET /api/colaboradores`
```json
// 200
[{
  "id": 1,
  "nome": "Ana",
  "matricula": "01",
  "tag_uid": "A1B2C3D4",
  "cargo": "Artist",
  "acesso_sala": true,
  "ativo": true,
  "na_sala": false,
  "entrou_hoje": true,
  "tempo_hoje_segundos": 3600
}]
```

### `POST /api/colaboradores` · `PUT /api/colaboradores/<id>`
- `nome`, `cargo`: dados do colaborador.
- `matricula`: identificação na empresa.
- `tag_uid`: código do crachá.
- `acesso_sala`: `true` se pode entrar na sala.
- `ativo`: `false` bloqueia sem excluir.
```json
// body
{ "nome": "Ana", "matricula": "01", "tag_uid": "A1B2C3D4", "cargo": "Artist", "acesso_sala": true, "ativo": true }
// 200
```

### `DELETE /api/colaboradores/<id>` → `200`

### `GET /api/eventos`
Eventos do dia (padrão) ou filtrados via query string (`?data=YYYY-MM-DD` ou `?todos=true`), mais recentes primeiro. O front monta a tela de logs e a de monitoramento filtrando por `resultado`.
```json
// 200
[{ "id": 1, "data_hora": "2026-10-28 19:15:02", "tag_uid": "A1B2C3D4", "nome": "Ana", "resultado": "ENTRADA" }]
```
"Dentro da sala" = colaboradores cujo último evento do dia é `ENTRADA`.

---

## Pandas → Servidor

### `GET /api/eventos.csv`
Todos os eventos.
```
id,data_hora,tag_uid,nome,resultado
```

---

## Depois (v2)
Sincronizar os eventos offline com o servidor, autenticar a Pi, usar `event_id` para evitar duplicados e criar uma rota `/api/monitor` dedicada.
