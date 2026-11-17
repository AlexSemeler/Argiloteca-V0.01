# Cliente ArgiloClay RAG

`RagClient` isola o transporte HTTP do Flask/Invenio. O processo da
Argiloteca não carrega modelos de linguagem e o cliente não registra perguntas,
respostas ou cabeçalhos.

## Configuração

- `ARGILOTECA_DRX_RAG_URL`: URL-base do serviço; padrão
  `http://127.0.0.1:7860`.
- `ARGILOTECA_DRX_RAG_TIMEOUT`: timeout em segundos; padrão `8`, limitado ao
  intervalo de `1` a `30`.

Os endpoints remotos permanecem `/api/v1/drx/status` e `/api/v1/drx/query`.
Na Argiloteca, os endpoints compatíveis continuam sendo
`/argiloteca/drx/rag/status` e `/argiloteca/drx/rag/query`.

## Erros

- entrada inválida: HTTP 400;
- indisponibilidade ou timeout: HTTP 503;
- JSON remoto inválido: HTTP 502;
- erro HTTP remoto: status preservado entre 400 e 599.

Uma falha do RAG não interfere nas rotas convencionais do painel DRX. As
respostas são evidência auxiliar e não representam confirmação mineralógica.
