# Repositórios OAI e PDFs — administração local

**Atualização em 01/11/2026:** os ajustes foram implantados em produção. Consulte o [guia produtivo](admin_production.md). As evidências abaixo mantêm seu escopo histórico local.

Entrega de homologação local, conferida em 31/10/2026. Entrada: [Importação de repositórios](https://127.0.0.1:5101/administration/repositories/); [PDFs](https://127.0.0.1:5101/administration/repositories/pdfs/); [publicação](https://127.0.0.1:5101/administration/repositories/publication/). Exige administrador. A interface funciona em português e inglês e herda o fluxo OpenAlex/PANGAEA/Mendeley.

## Fontes e busca

| Fonte | Endpoint OAI-PMH | Conjunto padrão | Identidade |
| --- | --- | --- | --- |
| LUME UFRGS | `https://lume.ufrgs.br/oai/request` | `com_10183_2`, teses e dissertações | Handle `10183/n` |
| UFSC | `https://repositorio.ufsc.br/oai/request` | Todos | Handle `123456789/n` |

O módulo usa `ListRecords` e `metadataPrefix=oai_dc`, conforme o [protocolo OAI-PMH](https://www.openarchives.org/OAI/openarchivesprotocol.html). OAI-PMH coleta metadados; o filtro por palavras é aplicado **no catálogo local**, sem busca remota por palavras ou raspagem para descobrir registros. A interface oferece somente essas duas fontes cadastradas. Outro repositório exige adaptação explícita de endpoint, identidade e hosts permitidos.

Há três modos: um dos mesmos 81 argilominerais, texto livre ou ambos. No modo combinado, as designações exatas em português/inglês do mineral são alternativas e a expressão livre é exigida por `AND`. Exemplo: Caulinita + `floculação` produz `("Kaolinite" OR "Caulinita") AND (floculação)`. A busca considera título, assunto e descrição, ignora maiúsculas/acentos e aceita `AND`, `OR`, `NOT`, parênteses, frases entre aspas, AND implícito e `*` ao final de uma palavra. Use os operadores em maiúsculas. Texto livre: até 500 caracteres.

Controles:

- Resultados por termo: 1–100; máximo de termos: 1–81; deslocamento: 0–80, aplicado à opção de todos os termos em ordem portuguesa. Para um mineral específico, deslocamento zero.
- Páginas novas: 0–100, padrão 10. Zero pesquisa só o catálogo existente. Cada nova busca ou **Continuar coleta com a mesma busca** acrescenta páginas ao mesmo catálogo; a continuação usa 10 quando a busca anterior tinha zero.
- Conjunto vazio no formulário usa o padrão da fonte. `__all__` seleciona todo o LUME; internamente fica conjunto vazio, preservado na revalidação pelo agente.
- Datas `AAAA-MM-DD` limitam a **modificação OAI**, não a publicação. Fonte, conjunto, período e ciclo identificam o catálogo. Alterar qualquer um cria catálogo distinto; ciclo: 1–99999.
- Ao concluir um ciclo ou receber `badResumptionToken`, aumente o ciclo para atualizar/recomeçar. Os anteriores permanecem preservados.

Confira a cobertura exibida antes de interpretar ausência de resultados. Uma coleta parcial cobre apenas as páginas recebidas, mesmo quando o lote de busca terminou. Registros marcados como excluídos na fonte ficam no catálogo de auditoria e saem da busca; isso não exclui registros nativos. CAPTCHA, HTML e erros OAI são falhas, não buscas vazias bem-sucedidas. Apenas `noRecordsMatch` constitui vazio intencional aceito.

## Revisar, importar e publicar

1. Colete, acompanhe o histórico e prepare a revisão de um lote concluído com resultados. A revisão é paginada em até 20 linhas e apresenta identidade, validação nativa, procedência, alertas e comunidades propostas.
2. Confira metadados e corrija campos descritivos pelo formulário JSON. A correção gera outra revisão; identidade e procedência não são editáveis por esse caminho. Dados obrigatórios ausentes/ambíguos impedem importação.
3. Selecione até 20 registros aptos na página, confira/desmarque comunidades e aceite o consentimento de importação. Correspondência exata por DOI/Handle atualiza o mesmo registro; ausentes geram rascunhos. Os metadados fornecidos são sobrescritos no correspondente; campos científicos, arquivos e comunidades anteriores são preservados pelo serviço nativo compartilhado.
4. Em publicação, gere e confira a prévia, selecione lote de 100 (padrão), 200 ou 500 e confirme separadamente. Somente rascunhos aptos são publicados, com a visibilidade atual. A execução mantém relatório e backup ZIP verificado por SHA256. Baixe/conserve esses artefatos para auditoria.

Relatórios de revisão/importação e publicação estão disponíveis em JSON/CSV. A prévia já confirmada aponta para a execução existente. Não confunda tarefa PDF, importação de rascunho e publicação: são decisões independentes.

Regras bibliográficas importantes:

- Handle é obrigatório e deve concordar entre identificador OAI e `dc:identifier` institucional. DOI é aceito somente quando declarado integralmente como identificador; citação em descrição/relação não define identidade. Mais de um DOI declarado bloqueia o item. URLs institucionais correspondentes e Handles explícitos compartilham identidade na detecção nativa; URLs malformadas são ignoradas.
- Uma única data distinta em `dc:date`, sem horário, pode fornecer ano, ano-mês ou data completa, mantendo sua precisão. Datas conflitantes ou ausentes bloqueiam. Timestamps de depósito/acesso e `datestamp` OAI não viram data de publicação.
- `Sobrenome, Nome` separa os componentes declarados do autor. Sem vírgula, o nome é preservado e a validação nativa pode exigir correção de sobrenome; o módulo não adivinha essa divisão.
- Tese/dissertação é mapeada para `publication-dissertation`. Metadados adicionais e XML permanecem na procedência. Não são inferidos `custom_fields` científicos. Rascunhos novos contêm apenas metadados, com arquivos desabilitados.
- “Open Access” é declaração de acesso, não licença de reutilização. URIs Creative Commons reconhecidas, se presentes, são mapeadas; os direitos originais permanecem auditáveis.

## Baixar PDFs vinculados

Na revisão, a seção **Documentos para download** tem caixas de seleção e consentimento próprios. Selecione até 20 itens e inicie o download. Um item bloqueado por metadados pode ter seu PDF solicitado; isso não o torna apto para importação. Acompanhe em **PDFs baixados** e use o download verificado do resultado.

A descoberta inspeciona identificadores e a página oficial do mesmo Handle (`citation_pdf_url` e links). Só aceita caminhos de bitstream PDF do mesmo item e repositório, em hosts cadastrados, normalizados para HTTPS. Redirecionamentos são revalidados; login, CAPTCHA e declarações reconhecidas de acesso restrito/embargo impedem a obtenção. Não há credenciais nem contorno de acesso.

Limites: cinco candidatos por item, 100 MiB por arquivo e orçamento de 500 MiB transferidos por tarefa. O download em fluxo usa temporário e verifica assinatura `%PDF-`, marcador `%%EOF`, tamanho declarado quando presente e SHA256. Essa verificação **não é validação integral da estrutura interna do PDF**. Temporários são removidos ao encerrar a tentativa.

Os arquivos ficam privados em `pdfs/blobs/<SHA256>.pdf`, com manifesto em `pdfs/jobs/<id>/manifest.json`, dentro da fila do módulo. Conteúdo idêntico ocupa um arquivo, com aliases das fontes no relatório. Cada download servido verifica tamanho e hash novamente; adulteração impede entrega. A interface mostra direitos, procedência e resultados parciais/indisponíveis. Uma nova tentativa gera outra tarefa e relatório, preservando conteúdo existente; há checkpoints por registro, sem retomada por byte.

PDF baixado permanece em staging administrativo: não vira anexo nativo, publicação, ingestão ou entrada de RAG automaticamente. O acesso anônimo aos downloads é recusado. URLs resolvidas do relatório privado podem incluir identificadores transitórios do servidor; para citar o item, use a URL estável do Handle.

## Runtime e operação

`argiloteca/repositories/__init__.py` habilita o módulo por padrão apenas quando `SITE_UI_URL` aponta para loopback (`127.0.0.1`, `localhost`, `::1`). `ARGILOTECA_REPOSITORIES_ENABLED` em configuração ou ambiente permite decisão explícita; no ambiente, o valor habilitador é `true`. A fila vem da configuração `ARGILOTECA_REPOSITORIES_ROOT`, padrão `<ARGILOTECA_OPENALEX_QUEUE>/repositories`.

O bind mount existente do pacote, somente leitura no contêiner, disponibiliza o código local. Esta entrega recarregou serviços locais; não introduziu migração nem alteração de produção. POST exige CSRF; respostas administrativas usam `private, no-store` e `noindex`. As tarefas `oai_extract`, `oai_prepare`, `oai_import`, `oai_publish_scan`, `oai_publish` e `oai_pdf` usam o dispatcher compartilhado e os serviços nativos de importação/publicação.

O agente host lê a fila e acessa as fontes públicas, sem listener ou credenciais. A partir de `argiloteca-rdm14-hml`:

```sh
python3 scripts/repositories-local-agent.py
```

Para registrar o agente na sessão gráfica atual do macOS:

```sh
python3 scripts/install-repositories-host-agent.py
```

O plist e os logs ficam em `data/openalex-admin-queue/repositories`, sem instalação em `~/Library/LaunchAgents`. Após logout/reboot, registre novamente. O instalador tem repetição limitada para a corrida de desligamento do launchd. Não execute outro agente concorrente: o arquivo `host.lock` aplica exclusão. Se configurar fila alternativa, alinhe a configuração do aplicativo e `--queue` do agente; o instalador usa a fila padrão do workspace.

Diagnóstico: confira o status do agente na tela e `heartbeat.json` (offline após 60 s), `agent.stdout.log`, `agent.stderr.log`, histórico, arquivos `<id>.request.json`/`<id>.result.json` e manifestos. Catálogos SQLite ficam em `catalogues/<hash>/`, com XML bruto, recibos SHA256 e estado transacional de `resumptionToken`; a continuação OAI envia somente verbo/token. Lotes `lotes/oai_<id>` preservam parâmetros, metadados e hashes. Não edite artefatos preservados para forçar a retomada.

Falha UFSC por verificação de acesso exige acesso institucional/VPN autorizado e nova tentativa após liberação externa. Não é confirmação de ausência de registros. Para token expirado, aumente o ciclo; para lote alterado, prepare nova extração/revisão. Resultados já preservados não devem ser apagados para disfarçar falhas.

`scripts/verify-repositories-local.py --extraction <id>` roda dentro do Invenio local e cria revisões de verificação. A opção `--exercise-import` **cria, atualiza e publica um registro real**, somente no endereço local e quando a identidade ainda não existe. É ensaio de ciclo de vida, não rotina pós-importação nem verificação somente leitura.

## Evidência e limites

Artefatos em `output/repositories-admin-20261031/`; as verificações não foram reexecutadas neste passe documental:

- `verified-interface.json`: PT/EN, 81 termos, recusa anônima/CSRF e adulteração; coleta LUME `1d9e4ba896744632997905ebd5185ec2`, dez páginas, 1000 entradas, 997 ativas e três excluídas, ainda parcial. Caulinita + floculação encontrou [Handle 10183/1970](https://lume.ufrgs.br/handle/10183/1970). Criação `99b73eb898854c0da01a74b038c27606`, atualização `4317cd0ca26f4c299b6ce46d47c4efe9` e publicação `cb3c36144903460e8becef1dde05bf90` preservaram o PID local `ka9qq-a7m11`, com comunidade Caulim-Serpentina e arquivos desabilitados. Backup SHA256: `e161ae6dfd9fe61fe74b303b4a06ec85f8cd3427493a2b464e2c22c69ff03f33`.
- `pdf-verification.json`: tarefa real `17ce99d793c144ca881cef8a05c8cdf4`, 1.538.883 bytes, SHA256 `b87a220e58fdf578b5103bfdc5b6d17b7b24441cde934d019f04c0d124b3c145`; dois links oficiais deduplicados em um arquivo. Download administrativo HTTP 200, anônimo recusado, adulteração recusada e registro nativo ainda sem arquivos. O arquivo baixado pelo navegador em `output/playwright/smoke/repositorio-b87a220e58fdf578.pdf` tem o mesmo hash.
- O mesmo relatório registra UFSC `6dbd47728fb14031b89b543379ec239e` como falha `AccessBlocked`: HTTP 200 com desafio HTML. O adaptador UFSC tem cobertura com XML sintético; coleta e PDF reais UFSC permanecem sem validação por bloqueio externo.
- `runtime-tests.log`: 35 testes; `openalex-regression.log`: 156; `other-extractors-regression.log`: Mendeley 27 e PANGAEA 16; **234 testes distintos aprovados**, registrados também em `source-manifest.json`. A tentativa ampla inicial teve sete falhas de fixtures de template; a execução final OpenAlex usou caminhos reais e passou. `client-tests.log` é subconjunto da suíte do módulo e não deve ser somado novamente.
- `detector.json` contém `[]`; avisos de CSS em Jinja limitam a cobertura automática de cores. A revisão independente `.impeccable/review/repositories-admin/finish-review.md` registrou **`disposition: ship`** para acabamento visual e clareza da extensão, com nove capturas desktop/mobile de índice, revisão, PDF, publicação e UFSC bloqueada. Não certifica plataforma inteira, segurança ou fontes externas.

Não há promessa de coleta exaustiva do corpus. Produção, carga, restauração efetiva de backup, exportação XML do registro nativo, RAG e anexação automática de PDFs permanecem fora desta entrega.

Fontes de implementação conferidas: `argiloteca/repositories/{__init__,client,network,workflow,views,pdfs,pdf_views,publication_views}.py`; quatro templates `admin_repositories*.html`; dispatcher `argiloteca/openalex/tasks.py`; scripts de agente, instalação e verificação citados acima. O sistema visual existente foi preservado, sem novos ativos ou identidade.
