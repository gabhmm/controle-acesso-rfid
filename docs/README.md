# Documentação histórica

Estes documentos registram o planejamento e as versões anteriores do sistema. **A referência atual é o [README da raiz](../README.md).**

| Documento | Descreve | Ainda vale? |
| :--- | :--- | :--- |
| [api contratos.md](api%20contratos.md) | Contrato da API v1 | Parcialmente. As rotas de colaboradores e eventos continuam; `POST /api/validar` e a Pi consultando a API a cada 3 minutos não existem mais |
| [guia_testes_api.md](guia_testes_api.md) | Roteiro de testes da API v1 | Parcialmente, pelos mesmos motivos |
| [mestre-jedi/](mestre-jedi/) | Framework de planejamento usado no projeto (PRD, tech spec, tarefas) e os documentos das versões v1 e v2 | Como registro do planejamento. Na versão atual, a Pi não usa Redis nem API: recebe a lista de colaboradores e envia os eventos só pelo RabbitMQ |
