# Administração PANGAEA na homologação local

Extensão da administração OpenAlex para buscar metadados públicos do PANGAEA, preparar revisões, criar ou atualizar rascunhos por DOI e publicar mediante confirmação separada. A implementação e as evidências de 31/10/2026 referem-se somente a `https://127.0.0.1:5101`. A implantação produtiva posterior possui guia e evidências próprios, indicados abaixo.

**Atualização posterior em 31/10/2026:** o mesmo módulo foi implantado em produção com agente Linux. Consulte o [guia produtivo](pangaea_admin_production.md). As evidências abaixo continuam descrevendo a entrega local.

## Operação

1. Acesse `/administration/pangaea/` como administrador. As páginas oferecem português e inglês (`?ln=pt` ou `?ln=en`); POSTs exigem CSRF. A navegação reúne nova busca, lotes, publicação e histórico.
2. Escolha um dos mesmos **81 argilominerais do OpenAlex**, informe uma expressão livre ou combine ambos. O termo livre não modifica o vocabulário. Frases entre aspas e operadores `AND`/`OR` são enviados ao mecanismo público de busca.
3. Para um teste pequeno, use resultados por termo = 1, máximo de termos = 1 e deslocamento = 0. Resultados por termo aceita 1–100; a seleção “Todos” percorre até 81 termos, a partir do deslocamento 0–80, em ordem do título português. Para um mineral específico, o deslocamento deve ser zero. Sem vocabulário, máximo e deslocamento não alteram a consulta livre.
4. Aguarde a coleta terminar e prepare a revisão do lote. Limite zero inclui todos os datasets; limite 1 permite uma revisão pequena. A preparação preserva os arquivos de origem.
5. Filtre a revisão por título/identificador e situação. As tabelas mostram até 20 itens por página. Abra o título para conferir DOI, problemas, payload e dados de procedência. Um registro bloqueado exige correção conferida na fonte; ele não pode ser importado.
6. Se necessário, envie uma correção descritiva em JSON, por exemplo `{"publisher":"PANGAEA"}`. Isso cria outra revisão, mantendo a anterior. Identificadores não são corrigíveis por esse formulário; a identidade DOI permanece vinculada à fonte. Não preencha datas ou outros dados por suposição.
7. Selecione os registros aptos e as comunidades propostas permitidas ao administrador, confira o consentimento e importe. Cada envio aceita até 20 registros. Ausência de correspondência temática não exclui o dataset da revisão nem inventa comunidade.
8. Em **Publicar rascunhos em lote**, escolha a revisão/importação de origem e gere a prévia. Confira DOI, validação nativa, arquivos, comunidades e acesso antes de confirmar a publicação de todos os aptos. O tamanho padrão é 100; opções: 100, 200 e 500. Esta confirmação é independente da importação.

Exemplos de consultas:

| Entrada | Consulta gerada |
| --- | --- |
| Apenas livre: `XRD OR "X-ray diffraction"` | A expressão livre, sem inclusão de termo do vocabulário |
| Apenas Caulinita | `("Kaolinite" OR "Caulinita") -type:series -type:bundled` |
| Caulinita + `DRX OR XRD` | `(DRX OR XRD) AND ("Kaolinite" OR "Caulinita") -type:series -type:bundled` |

Os termos inglês/português são agrupados com `OR`; o texto livre se combina ao grupo com `AND`. A exclusão de séries e conjuntos agrupados é aplicada às consultas com vocabulário. O limite “deslocamento” percorre termos do vocabulário, não páginas remotas de resultados: cada consulta usa `q`, `count` e `offset=0` no endpoint público `https://www.pangaea.de/advanced/search.php`.

## Agente no Mac e armazenamento

O navegador agenda tarefas no diário compartilhado `OpenAlexJob`; o Celery despacha os tipos `pan_extract`, `pan_prepare`, `pan_import`, `pan_publish_scan` e `pan_publish`. A coleta externa usa uma ponte local no Mac, por arquivos JSON, sem listener ou credenciais próprios. Os demais passos utilizam o runtime Invenio e os serviços nativos já empregados pelo OpenAlex.

Na pasta `argiloteca-rdm14-hml`, execute uma das opções:

```sh
python3 scripts/pangaea-local-agent.py
# Ou registre o processo da sessão gráfica atual:
python3 scripts/install-pangaea-host-agent.py
```

O instalador escreve `data/openalex-admin-queue/pangaea/br.argiloteca.pangaea-host.plist` no workspace, com permissão `0600`, e faz `launchctl bootstrap` no domínio `gui/<uid>`. O job `br.argiloteca.pangaea-host` tem `RunAtLoad`/`KeepAlive`; stdout/stderr ficam junto à fila. **Não há instalação em `~/Library/LaunchAgents`: execute o instalador novamente após logout/reboot para registrar a nova sessão.** Para interromper a sessão atual, use `launchctl bootout gui/$(id -u)/br.argiloteca.pangaea-host`.

O agente aceita `--queue`, `--vocabulary` e `--once`. Seus padrões são `data/openalex-admin-queue/pangaea` e `app_data/vocabularies/argilominerais.jsonl`. O app usa `ARGILOTECA_PANGAEA_ROOT`, cujo padrão é `<ARGILOTECA_OPENALEX_QUEUE>/pangaea`. A configuração local de fila compartilhada e a montagem host/container precisam apontar para os mesmos arquivos. O vocabulário do app vem da release de extrator OpenAlex existente; o digest deve coincidir com o do agente e a contagem deve ser 81.

Um heartbeat de até 60 segundos indica disponibilidade; a interface recusa nova coleta se estiver offline. A fila guarda `<job>.request.json`, `<job>.result.json`, `heartbeat.json` e `host.lock`. Lotes `lotes/pan_<id>/` contêm `busca.json`, respostas `search_*.json`, `metadata_<id>.json`, `records.json` e `resultado.json`, com hashes dos insumos. As revisões SQLite ficam em `<ARGILOTECA_OPENALEX_QUEUE>/previews/`. São metadados e artefatos de auditoria; o coletor não baixa arquivos de dados científicos dos datasets.

## Fonte, mapeamento e preservação

A adaptação reutiliza do V57 o endpoint de busca, o vocabulário bilíngue, candidatos DOI e o fluxo revisão → rascunho → publicação. Os três scripts legados foram lidos como **dados de referência**, sem executá-los nem copiar credenciais. Seus caminhos e SHA256 estão em `output/pangaea-admin-20261031/legacy-sources.json` na raiz do repositório.

O adaptador `argiloteca-pangaea/1.0` prefere os metadados estruturados JSON-LD do dataset à extração frágil de HTML. Só aceita como identidade primária o DOI `10.1594/PANGAEA.<n>` declarado em `URI` pelo resultado de busca, e exige correspondência nos metadados recebidos. Um DOI citado em outro campo não substitui essa identidade.

Referências primárias consultadas na implementação: [PANGAEA — Data Access and Reuse](https://wiki.pangaea.de/wiki/Data_Access_and_Reuse) e [busca no cliente oficial pangaeapy](https://pangaea-data-publisher.github.io/pangaeapy/_modules/pangaeapy/panquery.html).

| Origem JSON-LD | Destino Invenio |
| --- | --- |
| `name`, `datePublished`, `creator`/`author` | Título, data de publicação e criadores, com nomes/ORCID quando fornecidos |
| DOI primário e URL do dataset | Identificadores DOI e URL; tipo de recurso `dataset` |
| `publisher` | Editor; padrão bibliográfico `PANGAEA` quando ausente |
| `description`/`abstract`, `keywords` | Descrição escapada e assuntos |
| `inLanguage`, `license` | Idioma reconhecido e licença com URL HTTP(S), quando disponíveis |
| `spatialCoverage` | Local e ponto geográfico somente com coordenadas válidas |

Metadados não mapeados permanecem no JSON de origem e na procedência da revisão, junto da consulta, termo, resposta da busca, URL e hash. Não há conversão automática em amostras, análises, resultados mineralógicos ou campos científicos `arg:*`. Título, criadores e data ausentes bloqueiam; licença ausente gera alerta, sem licença padrão inventada. Novos registros são bibliográficos, com arquivos desabilitados e acesso público explícito no payload proposto, sujeito à revisão.

A importação compartilha o inventário DOI, claims e transações nativas do OpenAlex. Uma correspondência única atualiza o mesmo PID; conflitos múltiplos ou identidade divergente interrompem a escrita. Campos bibliográficos recebidos substituem os correspondentes, enquanto campos ausentes do payload permanecem. Identificadores são unidos; `custom_fields`, arquivos/media existentes, acesso, propriedade e provedores PID ficam sob preservação/controle nativo. Comunidades já existentes são mantidas e somente destinos propostos e permitidos podem ser acrescentados. Isso não implica que todo campo bibliográfico curado esteja imune à atualização: confira as diferenças antes de importar.

Prévia, lote e payload são verificados por hash. A confirmação repetida da mesma seleção reutiliza a tarefa; checkpoints de registros concluídos permitem retomada. Coleta com falha cria nova tarefa ligada à coleção original e reaproveita respostas já preservadas; alteração de parâmetros/vocabulário ou adulteração de lote concluído exige nova coleta/revisão. A retomada de tarefas com falha fica disponível ao próprio autor.

A publicação usa prévia imutável e confirmação vinculada ao hash do plano. Antes da escrita, cada lote recebe backup ZIP verificado; o download também confere SHA256. Rascunhos alterados desde a prévia são separados para nova revisão; registros já publicados são reconhecidos pelo mesmo identificador. A operação mantém metadados atuais, arquivos, acesso e comunidades e registra resultados por item. Backups, relatórios JSON/CSV e histórico ficam disponíveis na interface. Backup verificado não equivale a ensaio de restauração.

## Interface herdada

As três telas `admin_pangaea*.html` estendem a administração existente, usam os SVGs nativos e reutilizam `admin-openalex.css`/JS. Mantêm Catamaran/Lato, marrom/laranja, formulários e tabelas Semantic UI, sem novo sistema visual. O workspace tem largura máxima de 1160 px; foco visível, quebra de identificadores e rolagem de tabelas são herdados. Abaixo de 700 px, campos e filtros empilham; abaixo de 767 px, rótulos de células preservam o contexto. O formulário continua funcional sem JavaScript; o script atualiza o progresso e evita envios repetidos durante o processamento.

## Evidências de 31/10/2026 e limites

Os arquivos abaixo ficam em `output/pangaea-admin-20261031/`, na raiz do repositório:

- `client-tests.log`: **16 testes aprovados** do adaptador/consultas, incluindo identidade primária, seleção exata e três modos.
- `shared-regression.log`: **49 testes aprovados** de componentes compartilhados. Não substituem uma simulação de grande carga ou recuperação após falha do host.
- `verified-interface.json` e `interface-tests.log`: PT/EN, 81 termos, acesso anônimo recusado, CSRF, três modos, lote real apto e bloqueio por data ausente, adulteração recusada e sugestões de comunidades. Essa execução sem importação manteve as contagens nativas iguais; a prova de escrita é a separada abaixo.
- `live-search.json`: busca real pelo navegador → Celery → agente host → `completed`, tarefa `6d9ae39c0ff7449db058d7786e915491`, Caulinita + `"Aegean Sea"`, um dataset. Digest de vocabulário: `144dace3b1a78c4ae714ea7c2cce2ddd2ceb6a55cf0230387c9310204ea6f750`.
- `publication-verification.json`: conferência independente do registro nativo e API anônima HTTP 200. DOI `10.1594/PANGAEA.810743` criou o rascunho na tarefa `4718ebf386314fca9616f6bd1142b659`, foi atualizado por `4d2c69a28aaa43c4aa361e779f646ead` no mesmo PID **`b2b0y-smv69`**, e publicado por `0bd95e846ad242bab75d13f98b3055f0`. A prova registra arquivos desabilitados e duas comunidades preservadas: Caulim-Serpentina e Cloritas. Backup `0.zip`, 4300 bytes, SHA256 `e7cddf6250be6cf32cc50374c0392af7f5a148af594207dbb3364e070e4937fc`.
- O dataset real `10.1594/PANGAEA.984005` ficou bloqueado por ausência de data de publicação; nenhuma data foi inferida.
- `runtime.json`: Python 3.14.7, InvenioRDM 14.0.4, PostgreSQL e OpenSearch 2.19.5; é inspeção de configuração/runtime, não prova de persistência de todos os campos, exportação XML ou OAI-PMH.
- `detector.json`: lista vazia (`[]`). A detecção automática não substitui inspeção visual.
- `final-smoke.json`: rotas PANGAEA PT/EN, publicação e OpenAlex existente HTTP 200; acesso anônimo recusado, relatório JSON transmitido válido, 81 termos, agente online e busca real pelo navegador concluída.

As seis capturas exigidas estão em `.impeccable/review/pangaea-admin/`: `desktop-index.png`, `desktop-review.png`, `desktop-publication.png`, `mobile-index.png`, `mobile-blocked.png` e `mobile-publication.png`. A primeira revisão independente das seis capturas pediu correção porque o mascote sobrepunha consentimento/status em desktop. A guarda de posicionamento estático já usada no OpenAlex foi estendida ao PANGAEA e houve nova captura. O veredito atualizado em `finish-review.md` é **`disposition: ship`**, restrito à resolução dessa única correção: consentimento e status de publicação visíveis no desktop, sem regressão visível nos estados móveis inspecionados. Esse segundo passe não reabriu a avaliação original de toda a superfície.

O script `scripts/verify-pangaea-local.py` verifica o endereço local antes de operar. Seu modo padrão testa interface/revisão sem importar; `--exercise-import` **escreve e publica um dataset real ausente**, e não deve ser usado como comando rotineiro sobre um acervo já importado. Ele também gera estado de sessão local temporário para captura; não distribuir esse arquivo como documentação. Os arquivos temporários de autenticação usados na validação foram removidos ao encerrar a captura. A documentação foi derivada do código e dos artefatos citados; seus testes não foram reexecutados nesta etapa documental.

A entrega local descrita acima não incluiu implantação produtiva, ensaio de restauração de publicação, carga ou exportação/OAI-PMH. A implantação posterior em produção está registrada separadamente no [guia produtivo](pangaea_admin_production.md), com seus próprios testes e limites.
