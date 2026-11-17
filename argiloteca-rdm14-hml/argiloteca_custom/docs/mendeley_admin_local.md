# Administração Mendeley Data na homologação local

**Atualização em 01/11/2026:** os ajustes foram implantados em produção. Consulte o [guia produtivo](admin_production.md). As evidências abaixo mantêm seu escopo histórico local.

Extensão da administração OpenAlex/PANGAEA para buscar metadados públicos de datasets do Mendeley Data, preparar revisões, criar ou atualizar rascunhos por DOI e publicar por confirmação separada. Esta entrega de **31/10/2026 é exclusivamente local**, em `https://127.0.0.1:5101/administration/mendeley/`. Produção depende da aprovação posterior do usuário; nenhum arquivo, configuração ou serviço produtivo foi alterado nesta entrega.

## Operação

1. Entre como administrador em `/administration/mendeley/`. Use `?ln=pt` ou `?ln=en` para português/inglês. POSTs exigem CSRF; as páginas administrativas não são públicas.
2. Escolha um dos mesmos **81 argilominerais do OpenAlex**, informe uma expressão livre ou combine ambos. O texto livre não altera o vocabulário. São aceitas palavras, frases entre aspas e operadores `AND`/`OR`, até 500 caracteres sem caracteres de controle.
3. Comece com resultados por termo = **1**, máximo de termos = **1** e deslocamento = **0**. Resultados por termo aceita 1–100. “Todos os termos” percorre até 81 entradas, ordenadas pelo título português, a partir do deslocamento 0–80. Para um mineral específico, use deslocamento zero. Sem vocabulário, máximo e deslocamento não alteram a consulta livre.
4. Aguarde a coleta concluir e prepare a revisão do lote. Limite de revisão zero inclui todos os datasets; limite 1 prepara uma revisão pequena. Preparar não modifica os arquivos de origem.
5. Na revisão, filtre por título/identificador ou situação; a paginação mostra até 20 itens. Abra o título para conferir identidade DOI, alertas, validação nativa, payload, procedência e diferenças em relação a registros existentes. Registros bloqueados não podem ser importados.
6. Corrija somente informação descritiva comprovada na fonte, em JSON, por exemplo `{"publisher":"Mendeley Data"}`. Cada correção cria outra revisão e preserva a anterior. DOI, identidade do dataset e versão não são corrigíveis por esse formulário. Não complete datas, nomes ou dados científicos por suposição.
7. Selecione os aptos, confira as comunidades propostas permitidas ao administrador e marque o consentimento de importação. Cada envio aceita até **20 registros**. Um dataset sem correspondência temática continua disponível para revisão; nenhuma comunidade é inventada.
8. Abra **Publicar rascunhos em lote**, selecione a revisão/importação de origem e gere a prévia. Confira DOI, estado nativo, arquivos, acesso e comunidades antes de confirmar a publicação de todos os aptos. Os lotes de processamento aceitam **100, 200 ou 500** itens, com padrão 100. Publicar exige confirmação independente da importação.

| Entrada | Consulta DataCite |
| --- | --- |
| Apenas livre: `XRD OR "X-ray diffraction"` | A expressão livre, sem termo de vocabulário |
| Apenas Caulinita | `("Kaolinite" OR "Caulinita")` |
| Caulinita + `DRX OR XRD` | `(DRX OR XRD) AND ("Kaolinite" OR "Caulinita")` |

Cada requisição usa `https://api.datacite.org/dois`, com `client-id=bl.mendeley`, `resource-type-id=dataset`, `sort=-published`, `page[size]` definido pelo limite e **`page[number]=1`**. O deslocamento percorre o vocabulário, não páginas remotas. A implementação coleta somente a primeira página de cada consulta; não é uma colheita exaustiva. Os resultados podem diferir da busca do site Mendeley e os filtros de repositório/tipo não são substituídos pelo texto livre.

## Ativação, agente e armazenamento

`argiloteca/mendeley/__init__.py` habilita o módulo por padrão somente quando o hostname de `SITE_UI_URL` é `127.0.0.1`, `localhost` ou `::1`. Uma configuração explícita `ARGILOTECA_MENDELEY_ENABLED` prevalece; na ausência dela, a variável de ambiente de mesmo nome é interpretada como habilitada apenas quando seu valor, sem distinção de caixa, é `true`. Ambientes remotos ficam desabilitados por padrão. A entrada lateral acompanha essa configuração.

Não houve migração de esquema. As tarefas reutilizam `OpenAlexJob`, com tipos `men_extract`, `men_prepare`, `men_import`, `men_publish_scan` e `men_publish`, despachados pelo Celery compartilhado. A coleta externa usa um agente no Mac, comunicando-se por arquivos JSON, sem listener, OAuth ou novas credenciais. Revisão, importação e publicação usam os serviços nativos Invenio já empregados pelo OpenAlex.

Na pasta `argiloteca-rdm14-hml`, execute uma das opções:

```sh
python3 scripts/mendeley-local-agent.py
# Ou registre o processo da sessão gráfica atual:
python3 scripts/install-mendeley-host-agent.py
```

O instalador grava `data/openalex-admin-queue/mendeley/br.argiloteca.mendeley-host.plist` no workspace, com permissão `0600`, e registra `br.argiloteca.mendeley-host` via `launchctl bootstrap` no domínio `gui/<uid>`. O job usa `RunAtLoad`/`KeepAlive`; stdout/stderr ficam junto à fila. **Não há instalação em `~/Library/LaunchAgents`: registre novamente após logout/reboot.** Para interromper a sessão atual:

```sh
launchctl bootout gui/$(id -u)/br.argiloteca.mendeley-host
```

O agente aceita `--queue`, `--vocabulary` e `--once`. Os padrões são `data/openalex-admin-queue/mendeley` e `app_data/vocabularies/argilominerais.jsonl`. O app usa `ARGILOTECA_MENDELEY_ROOT`, com padrão `<ARGILOTECA_OPENALEX_QUEUE>/mendeley`. A fila do host e sua montagem no container devem apontar para os mesmos arquivos. O app lê os 81 termos da release de extrator OpenAlex existente; agente e app devem ter a mesma contagem e digest do vocabulário.

Heartbeat com menos de 60 segundos indica disponibilidade; novas coletas são recusadas quando o agente está offline. A fila contém `<job>.request.json`, `<job>.result.json`, `heartbeat.json` e `host.lock`. Em `lotes/men_<id>/`, ficam `busca.json`, `search_*.json`, `concept_<dataset>.json`, `metadata_<dataset>_<versão>.json` quando aplicável, `records.json` e `resultado.json`. Revisões SQLite ficam em `<ARGILOTECA_OPENALEX_QUEUE>/previews/`. São metadados e artefatos de auditoria; **arquivos científicos dos datasets não são baixados**.

A montagem já existente do pacote completo em `docker-compose.argiloclay-fix.yml` expõe o código aos containers locais; não foi criado compose adicional. Os serviços locais foram recarregados. Isso não constitui implantação em produção nem configuração de host definitivo.

## Fonte, identidade e versões

O adaptador `argiloteca-mendeley/1.0` usa os depósitos públicos do Mendeley na **API JSON:API da DataCite**. A busca web Mendeley respondeu 403 e a busca da API nativa exigiu autenticação (401) durante a investigação; não foram utilizados scraping autenticado, API privada ou credenciais. Referências oficiais da implementação: [Mendeley Data API](https://data.mendeley.com/api/docs/) e [DataCite — API queries](https://support.datacite.org/docs/api-queries). O endpoint oficial [OAI Mendeley](https://data.mendeley.com/oai) não foi implementado.

A identidade exige DOI primário `10.17632/<10 caracteres alfanuméricos>[.versão]`, correspondência entre `id` e `attributes.doi`, cliente `bl.mendeley`, tipo `Dataset`, estado `findable` e URL HTTPS exata em `data.mendeley.com/datasets/<id>[/<versão>]`. DOI apenas citado em outro campo não substitui essa identidade. Respostas e relações DOI divergentes interrompem a coleta.

O agrupamento usa o identificador do dataset **dentro do lote**, reunindo resultados repetidos e preservando todas as consultas de origem. O DOI de conceito é consultado; quando declara relações `HasVersion`, a maior versão declarada é buscada e fixada no payload. Se as relações estiverem ausentes, uma versão descoberta é preservada com alerta `latest_unverified`; um registro legado somente com DOI de conceito permanece sem versão, com `version_missing`. Nunca é inventada a versão `.1`.

Esse agrupamento não é uma deduplicação global por conceito. O upsert nativo compara o **DOI exato**: uma versão diferente descoberta em outro lote pode criar outro registro. A revisão de duplicidades deve considerar esse limite.

## Mapeamento e preservação

| Origem DataCite | Destino Invenio |
| --- | --- |
| `titles`, `dates` com tipo `Issued` ou `publicationYear`, `creators` | Título, data e criadores, com nomes, ORCID e afiliações fornecidos |
| DOI primário e URL verificados | Identificadores DOI/URL, tipo de recurso `dataset`; versão somente quando declarada |
| `publisher` | Editor; padrão bibliográfico `Mendeley Data` se ausente |
| `descriptions`, `subjects` | Descrição escapada e assuntos |
| `language`, `rightsList` | Idioma reconhecido e direitos com URI HTTP(S), quando fornecidos |
| `geoLocations`, `sizes`, `formats` | Local/ponto com coordenadas válidas, tamanhos e formatos fornecidos |

Datas mantêm a precisão disponível: dia, mês ou apenas ano; não é inventado dia/mês. Criadores pessoais mantêm os componentes fornecidos; sobrenome não é inferido de nome completo. A validação nativa pode bloquear um autor pessoal sem `family_name`, mesmo havendo `name`. Título, criadores e data ausentes bloqueiam; licença ausente gera alerta, sem licença padrão.

Metadados não mapeados permanecem na resposta original e na procedência, com consulta, termo, DOI de conceito, versão, origem e hashes. Não são inferidos amostras, análises, mineralogia ou `custom_fields` científicos `arg:*`. Novos registros propõem arquivos desabilitados e acesso público, sujeitos à revisão. O campo `provenance.mapping` identifica o mapeamento bibliográfico DataCite JSON:API. Prévias históricas imutáveis dos testes podem conservar o rótulo textual anterior “JSON-LD bibliográfico”, com `provider` e `source_metadata` já identificando DataCite.

A importação reutiliza inventário DOI, claims, classificação de comunidades e transações do OpenAlex. Uma correspondência única atualiza o mesmo PID; conflito múltiplo ou identidade divergente interrompe a escrita. Campos bibliográficos recebidos substituem os correspondentes; ausentes do payload permanecem. Identificadores são unidos. `custom_fields`, arquivos/media, acesso, propriedade e provedores PID ficam sob as regras de preservação/controle nativo. Comunidades existentes permanecem e somente propostas permitidas podem ser acrescentadas. Confira diferenças: isso não torna todo campo bibliográfico curado imune a atualizações.

Lote, revisão e payload são conferidos por hash. Correções produzem outra revisão imutável. Repetir a confirmação da mesma seleção reutiliza a tarefa; checkpoints permitem retomar itens pendentes. Uma coleta com falha cria nova tarefa ligada à coleção original e reutiliza respostas preservadas. Parâmetros/vocabulário diferentes ou adulteração de lote concluído exigem nova coleta/revisão. A retomada de falha é restrita ao autor da tarefa.

A publicação usa prévia imutável e confirmação vinculada ao hash do plano. Antes de escrever, cada lote recebe backup ZIP verificado; o download também confere SHA256. Rascunhos alterados desde a prévia exigem nova revisão; registros já publicados são reconhecidos por identidade. Metadados atuais, arquivos, acesso e comunidades são preservados na publicação e o resultado é registrado por item. Interface, relatórios JSON/CSV e histórico permitem acompanhar as operações. Backup verificado não equivale a ensaio de restauração.

## Interface e evidências

As três telas `admin_mendeley*.html` estendem a administração existente e reutilizam SVGs, Semantic UI e `admin-openalex.css`/JS. Preservam marrom/laranja e Catamaran/Lato, sem nova identidade ou raster. O workspace tem largura máxima de 1160 px; foco visível, quebra de identificadores, rolagem contida e rótulos móveis de células são herdados. Campos/filtros empilham abaixo de 700 px e as células ganham contexto abaixo de 767 px. Formulários funcionam sem JavaScript; o script acompanha progresso e evita reenvio durante processamento. O mascote usa posicionamento estático neste blueprint, sem cobrir ações.

Evidências na raiz do repositório, em `output/mendeley-admin-20261031/`:

- `mendeley-runtime-tests.log`: **27 aprovados**. `shared-regression.log`: **56 aprovados** (OpenAlex 28, publicação 12, PANGAEA 16), somando **83 testes distintos**. Os 20 testes iniciais de `client-tests.log` são subconjunto dos 27. O primeiro ensaio compartilhado teve falha de ordem de importação do blueprint; o ensaio final inicializou o app completo e passou, com registro adicional em `openalex-regression.log`.
- `verified-interface.json`: PT/EN, 81 termos, três modos, acesso/CSRF, adulteração recusada e ciclo nativo de criação → atualização no mesmo PID → publicação. O bloqueio por data ausente foi exercitado com **fixture sintética**, não é alegação sobre um dataset real.
- Na coleta real `b2e852abb93a4fb0bbddbd9972c11a50`, dois datasets foram obtidos. `10.17632/4trtd6zbfn.1` ficou bloqueado por autor pessoal sem `family_name`, com alertas de licença/versão; não foi corrigido por inferência.
- `final-proof.json`: busca real pelo navegador → Celery → agente, Caulinita + `urea`, tarefa `d946983c3ce24d84843e1dee8a305d75`, concluída com um dataset; conferência independente do registro **`9gvyp-bvf52`**, DOI **`10.17632/p8k8774ksj.1`**, comunidade Caulim-Serpentina e arquivos desabilitados. Backup `0.zip`, 2917 bytes, SHA256 `036697ef059f6d95e0378142d3bc71bc6fcda41b3fe4d34e6c1422940ff9a5c3`.
- `anonymous-api.json`: registro publicado acessível anonimamente, HTTP 200. `final-http-smoke.txt`: seis rotas HTTP 200, cobrindo Mendeley PT/EN, publicação PT/EN, OpenAlex e PANGAEA. `source-manifest.json` registra os hashes do código inspecionado.

As seis capturas em `.impeccable/review/mendeley-admin/` são `desktop-index.png`, `desktop-review.png`, `desktop-publication.png`, `mobile-index.png`, `mobile-blocked.png` e `mobile-publication.png`. A revisão independente `finish-review.md` inspecionou todas e registrou **`disposition: ship`**, restrito à extensão visual/UX local. A captura de publicação mostra estado já confirmado; o consentimento anterior foi conferido no template. `detector.json` contém `[]`, mas avisos de resolução de stylesheet Jinja limitam sua cobertura de cores. Isso não constitui certificação geral de acessibilidade/contraste. O finding antigo de `buildPath` de outra superfície não foi alterado.

`scripts/verify-mendeley-local.py` deve rodar no runtime Invenio local e exige `--ready-extraction` e `--blocked-extraction`. O modo padrão cria tarefas/revisões e estado de sessão temporário, sem importar/publicar registros nativos. **`--exercise-import` escreve, atualiza e publica um dataset real local e só funciona quando o dataset ainda está ausente**; não é comando de rotina para repetir sobre o acervo existente. Arquivos temporários de sessão não devem ser distribuídos. Os arquivos de autenticação usados nesta validação foram removidos do host/container e a sessão de navegador dedicada foi encerrada.

Esta etapa documental conferiu código e artefatos já produzidos, sem reexecutar testes ou operações. Permanecem fora do escopo carga, restauração de backup, colheita exaustiva, prova de exportação XML/OAI-PMH e implantação em produção. A aprovação visual local não autoriza essas etapas nem substitui a aprovação produtiva solicitada pelo usuário.
