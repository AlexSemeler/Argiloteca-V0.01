# Seleção e remoção administrativa local

**Atualização em 01/11/2026:** os ajustes foram implantados em produção. Consulte o [guia produtivo](admin_production.md). As evidências abaixo mantêm seu escopo histórico local.

Guia da extensão concluída em homologação local em 01/11/2026. Abrange OpenAlex, PANGAEA, Mendeley, repositórios OAI, ORCID, vínculos DRX e biblioteca RAW. A interface usa a manutenção administrativa existente, com prévia, permissões nativas, backup verificado e auditoria. Não houve deploy em produção nem remoção de dados científicos preexistentes na validação.

## Selecionar e revisar

1. Abra a lista do módulo e marque os itens individualmente ou use **Selecionar tudo nesta página**. O botão alcança somente os itens selecionáveis da página atual; não seleciona resultados em outras páginas. Limpar a seleção desfaz essas marcações.
2. Escolha a operação na barra da lista e informe uma justificativa entre 5 e 500 caracteres. As caixas de remoção têm seu próprio formulário: não acionam a importação, a seleção de comunidade ou o download de PDFs. Nas revisões móveis, a coluna **Importar** identifica separadamente a importação.
3. Abra a prévia e confira cada alvo, efeito e bloqueio. Em RAW, confira também nomes, SHA-256, cópias, vínculos e registros preservados. Uma prévia pode conter itens liberados e bloqueados; a confirmação executa somente os liberados.
4. Para uma exclusão definitiva, digite **EXCLUIR** exatamente como exibido. Marque a confirmação de conferência dos efeitos e confirme a operação. O worker revalida o plano e as dependências e verifica o backup antes de alterar os dados.
5. Acompanhe o resultado individual e os detalhes da manutenção. Em **Auditoria e backups**, confira o registro da operação, a prévia e o ZIP com SHA-256. Backup disponível não significa restauração automática pela interface.

## Efeitos por objeto

| Objeto e ação | Efeito | Preservação |
| --- | --- | --- |
| Histórico: arquivar tarefa | Oculta a tarefa das listas atuais; pode ser restaurada. | Histórico, proveniência e registros importados. |
| Histórico: excluir tarefa | Exclui definitivamente a tarefa e seu snapshot. | Registros importados, arquivos de origem e reivindicações de identidade. |
| Revisão: excluir desta revisão | Exclui as linhas selecionadas da revisão e impede sua importação por ela. | Arquivos originais, registros já importados e histórico com backup. |
| Revisão: excluir do acervo | Aponta para o registro nativo já importado e prepara sua exclusão própria. Item ainda não importado deve usar a exclusão da revisão. | Conforme a prévia e os contratos nativos abaixo. |
| Registro publicado: excluir definitivamente | Exclui a versão selecionada, metadados, revisões e arquivos exclusivos, depois da verificação do backup. Não há restauração pela interface. | Backups, auditoria, identificadores reservados, arquivos compartilhados e DOI externos; os DOI externos não são cancelados. |
| Rascunho: excluir definitivamente | Exclui o rascunho e seus arquivos exclusivos. | A publicação existente, quando houver. |
| ORCID: remover vínculo | Remove somente o identificador ORCID das ocorrências de autoria selecionadas. | Autor, outros identificadores e publicações. Não exclui a pessoa nem a conta ORCID externa. |
| DRX: remover vínculos | Remove as associações DRX selecionadas e atualiza os metadados do registro. Na biblioteca, a ação abrange os vínculos ativos dos RAWs selecionados, dentro dos limites. | Arquivos RAW, curvas, análises e registros. |
| RAW: excluir arquivos | Exclui fisicamente os binários anônimos selecionados e suas cópias no módulo DRX; remove todos os vínculos ativos desses arquivos e os retira das consultas. | Registros, resultados históricos, originais privados e backups. |

A remoção de um vínculo DRX e a exclusão dos arquivos RAW são operações diferentes. Excluir uma tarefa de importação ou uma linha de revisão também não equivale a excluir o registro nativo.

## Bloqueios e limites

O acesso continua sujeito à administração e às permissões nativas do registro. A seleção é vinculada ao responsável autenticado e assinada; expira em **uma hora**. Se a seleção expirar, for alterada ou pertencer a outro responsável, recarregue a lista e selecione novamente. O plano aprovado é comparado com o estado atual antes da execução.

- Até **100 itens** por seleção e até **100 vínculos** envolvidos; divida a operação quando a expansão dos RAWs ultrapassar esse limite.
- Até **512 MiB** de binários RAW por operação, incluindo as cópias DRX; arquivo individual também deve respeitar esse teto.
- Edição nativa pendente em rascunho bloqueia a manutenção correspondente no publicado. Conclua ou resolva a edição antes de preparar outra prévia.
- RAW com envio nativo de curadoria é bloqueado até resolver esse envio. A prévia preserva os itens bloqueados.
- Checksum divergente, arquivo ausente ou montagem somente leitura interrompem a preparação/execução. Confira a origem e prepare nova prévia; não contorne o bloqueio.
- Em ORCID desatualizado, use o link para atualizar os autores e prepare nova seleção; o status **Bloqueado — será preservado** indica que aquela ocorrência não será modificada.

## Montagem local e recuperação

O arquivo [docker-compose.raw-maintenance-local.yml](../../docker-compose.raw-maintenance-local.yml) é um override **somente local**. Quando necessário, acrescente `-f docker-compose.raw-maintenance-local.yml` à mesma composição usada pela homologação, preservando os demais arquivos e configurações. Ele torna graváveis, em `web-ui`, `web-api` e `worker`, apenas as montagens `app_data/drx-library/files` e `data/drx/lifecycle-v1-20261020/raw` necessárias à remoção dos binários anônimos. Manifests, originais privados e o restante de `app_data` conservam as montagens somente leitura da composição base. Não é uma instrução de implantação em produção.

Se o detalhe informar **RAWs retirados da consulta; a limpeza dos binários precisa ser concluída**, a operação chegou ao checkpoint `cleanup`: a retirada das consultas já ocorreu, mas a limpeza física ainda precisa terminar. Confira resultado e backup e resolva a causa informada, como montagem sem escrita. Quando a execução está falha e pertence ao responsável atual, a UI oferece **Concluir exclusão dos RAWs**, que retoma essa limpeza. Não há retomada automática. Para a purga nativa, o estado equivalente oferece **Concluir limpeza da purga**; os metadados já foram excluídos. Confira o detalhe antes de preparar outra operação.

## Implementação e apresentação

`openalex/bulk_maintenance.py` registra prévia e aplicação sob `/administration/maintenance/bulk/`; `openalex/maintenance.py` reutiliza o motor auditado. `scientific/raw_removal.py` prepara o escopo RAW, verifica backups, retira associações e conclui a limpeza; `scientific/admin_raw_store.py` e `services/drx.py` filtram os itens retirados. Os templates compartilhados `_admin_bulk.html`, `admin_bulk_preview.html` e `admin_bulk_error.html` integram as listas; `admin_maintenance_job.html` apresenta resultados e recuperação. A flag `ARGILOTECA_ADMIN_ONTOLOGY_ENABLED` mantém o escopo local do módulo, conforme o [guia da ontologia](admin_ontology_local.md).

A extensão preserva marrom Argiloteca, laranja CPAA, cores de entidade, Catamaran/Lato, SVG e tabelas Semantic UI. A barra de operação usa os estilos locais `static/css/admin-bulk.css`; não constitui um sistema visual global. Em celular, as revisões usam rótulos por célula e ORCID mantém rolagem horizontal local com instrução. Foco visível e rótulos distinguem seleção de remoção e importação. `DESIGN.md` e `.impeccable/design.json` estavam ausentes e permaneceram ausentes.

## Evidências e limites da validação

Evidências em `output/admin-bulk-20261101/`, na raiz do projeto, e `.impeccable/review/admin-bulk/`. Este guia foi escrito a partir de fontes e resultados existentes, sem repetir navegador, testes ou detector.

| Evidência | Resultado registrado |
| --- | --- |
| `verification-summary.json`, `final-raw-unit-tests.log`, `raw-drx-tests.log`, `provider-regression.log` | 190 manutenção/OpenAlex + 93 DRX + 78 provedores (16 PANGAEA, 27 Mendeley, 35 repositórios) = **361 testes distintos aprovados**. A execução intermediária de 188 não é somada novamente. |
| `integration.json`/log e `raw-linked-integration.log` | Fixtures descartáveis; worker real removeu três binários anônimos novos e dois vínculos, preservou o registro temporário antes da limpeza da própria fixture, verificou backup, preservou três originais privados e impediu revinculação. Zero RAWs preexistentes excluídos. |
| `raw-copy-integration.log` | Dois binários sintéticos removidos, incluindo cópia DRX; snapshot público, biblioteca privada e consulta de download filtrados. Zero RAWs preexistentes excluídos. |
| `drx-routes-before.json` / `drx-routes-final.json` | 120 rotas estáticas DRX, iguais excluindo números de linha. |
| `final-browser-check.json`, `raw-browser-check.json`, manifesto de revisão | 28 estados em larguras 1440/390 px, com evidência PT/EN; seleções de importação e PDFs isoladas, sem erros de página ou escritas inesperadas nos checks registrados. Navegador abriu prévias, sem aplicar exclusões reais. |
| `keyboard-and-style.json`, `deleted-raw-routes.log` | Espaço seleciona/limpa, Enter seleciona página, documento móvel de 390 px; detalhe, curva, N/G/C e relatório dos três RAWs descartáveis retornaram 404 após a exclusão. |
| `.impeccable/review/admin-bulk/manifest.json` | SHA-256 conferidos no fechamento: 103/103 fontes e 28/28 capturas sem divergências. |

O [parecer inicial](../../../.impeccable/review/admin-bulk/finish-review.md) abriu as 28 capturas e pediu duas correções P2. O [parecer final](../../../.impeccable/review/admin-bulk/finish-verdict.md) reabriu oito capturas completas e concluiu **ship** para essas duas correções: rótulo móvel **Importar** e separação visual da recuperação ORCID/status bloqueado. Ele pontua somente esse lote e não repete nem amplia a revisão integral inicial.

Os logs registram avisos preexistentes sobre índices migrados de estatística ausentes e depreciação de faceta. Não há certificação integral de leitores de tela ou matriz de contraste. `detector.json` é `[]` de uma única execução anterior às últimas mudanças de cópias RAW e textos; não houve segundo detector. A validação apagou somente fixtures novas e descartáveis, preservando dados existentes, originais privados e backups. Nenhuma ação de produção foi executada.
