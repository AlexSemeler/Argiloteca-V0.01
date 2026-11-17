# Povoamento integrado — operação local

Este painel reúne OpenAlex, PANGAEA, Mendeley Data e OAI institucional na administração da Argiloteca. A entrega de 31/10/2026 foi implementada e validada apenas na instância local de homologação. Produção não foi tocada; sua implantação depende de aprovação futura.

Abra o [painel local em português](https://127.0.0.1:5101/administration/povoamento/?ln=pt) com uma sessão administrativa. As operações usam a proteção administrativa e os formulários com CSRF existentes. A extensão preserva Semantic UI, marrom/laranja, Catamaran/Lato, ícones e mascote herdados. Não adiciona raster de produto nem substitui o sistema visual global.

## Grão e interpretação

| Medida | Unidade e regra |
| --- | --- |
| Registros nativos | Uma linha por RID; publicado e sua edição em rascunho contam uma vez. A edição fornece o payload efetivo, inclusive autores. RIDs nativos distintos nunca são unidos silenciosamente. |
| Recuperados | Identidades presentes nas coletas sem correspondência nativa única; não significam importação ou publicação. A consolidação usa identificadores estruturados exatos DOI, OpenAlex ou Handle, nunca títulos ou homônimos. |
| Observações | Ocorrências de registros em lotes, inclusive repetições entre coletas. Não são novos registros do acervo. |
| Fontes | Vínculos de procedência com registros. Um registro pode pertencer a mais de uma fonte: não somar linhas de fontes para obter o total global. “Sem fonte identificada” permanece explícito. |
| Autores | Uma ocorrência por autor pessoal e posição no payload efetivo do registro. Grupos de nomes e ORCIDs distintos não são uma autoridade de pessoas únicas. |
| ORCID válido | Identificador normalizado com dígito verificador válido. Declaração na fonte e confirmação humana não equivalem à autenticação da identidade pelo titular. |
| PDF | Conteúdo distinto por SHA-256 registrado no staging privado OAI. Não implica anexo ao registro nem disponibilidade atual; o download verifica o arquivo. |

O snapshot é datado e imutável. Contagens vêm dele; tarefas recentes e últimas verificações de qualidade são consultadas no journal e têm datas próprias. Atualizar o retrato não inicia uma nova coleta externa, classificação, deduplicação, importação ou publicação.

## Fluxo dos dados

1. O trabalho `stats_scan` reutiliza o journal `OpenAlexJob` e a preparação estatística existente. Lê os metadados nativos publicados e rascunhos e os lotes configurados dos quatro importadores.
2. Cada lote exige marcador de coleta concluída, arquivo legível, contagem compatível e hashes de entrada preservados. Lotes incompletos, ausentes, alterados ou excluídos por configuração entram nos alertas; não viram sucesso com zero resultados.
3. A revisão mais recente em estado `review` de cada lote fornece suas correções, com conferência da origem. Os arquivos brutos permanecem intactos. Observações são relacionadas a registros por identificadores estruturados; ambiguidade é sinalizada para revisão.
4. A extensão acrescenta tabelas `p_*` ao SQLite imutável das estatísticas. Não cria modelo de banco de dados da aplicação nem exige migração do esquema nativo.
5. Autores, vínculos de fonte, lotes, alertas e hashes de PDFs alimentam o mesmo retrato. A interface e o CSV podem fixar seu identificador pelo parâmetro `analysis`.

Os caminhos de origem seguem `ARGILOTECA_OPENALEX_ROOT`, `ARGILOTECA_PANGAEA_ROOT`, `ARGILOTECA_MENDELEY_ROOT` e `ARGILOTECA_REPOSITORIES_ROOT`. A ativação exige a raiz OpenAlex configurada. Os serviços e o worker precisam carregar o mesmo pacote/configuração local para preparar os trabalhos. A aplicação desta entrega foi limitada ao pacote/templates locais e ao reinício do serviço local.

## Atualizar, filtrar e exportar

No painel, use **Atualizar retrato**. O formulário envia `POST /administration/povoamento/refresh`, cria ou acompanha o `stats_scan` pendente e abre seu acompanhamento. Aguarde a conclusão; em seguida, volte à visão integrada. Sem retrato disponível, essa é a ação oferecida pelo estado vazio. Um retrato indisponível ou incompatível exige nova preparação.

| Entrada local | Uso |
| --- | --- |
| [Visão integrada](https://127.0.0.1:5101/administration/povoamento/?ln=pt) | Resumo, fontes, lotes/cobertura, anos, qualidade e tarefas. |
| [Registros](https://127.0.0.1:5101/administration/povoamento/records/?ln=pt) | Uma linha por registro nativo ou identidade recuperada. |
| [Autores](https://127.0.0.1:5101/administration/povoamento/authors/?ln=pt) | Ocorrências pessoais em todos os provedores, inclusive coletas ainda não importadas. |
| [CSV de registros](https://127.0.0.1:5101/administration/povoamento/export.csv?ln=pt) | Exporta o retrato e os filtros selecionados. |
| [CSV de autores](https://127.0.0.1:5101/administration/povoamento/export.csv?ln=pt&view=authors) | Exporta as ocorrências e seu estado ORCID. |

As listagens aceitam `analysis`, `source`, `stage`, `q`, `year` e `status`; use os controles da interface para manter combinações válidas. Fontes: `openalex`, `pangaea`, `mendeley`, `lume`, `ufsc` e `unknown`. Etapas: `published`, `draft`, `editing` e `recovered`. Estados de autoria: `linked`, `missing`, `conflict` e `suggested`. O CSV inclui a coluna `analysis`, respeita os filtros e limita a exportação a 100.000 linhas; refine os filtros se necessário. A apresentação contém a rolagem horizontal das tabelas no celular.

Para reproduzir as contagens verificadas, fixe `analysis=8ed0acecb42b43ddabd3966ad54a7e85`. Um retrato posterior pode mudar as contagens e as chaves de ocorrência; mantenha o ID junto dos arquivos exportados.

## ORCID de autor nativo

Em **Autores**, escolha **Revisar ORCID** na ocorrência desejada. Para autores nativos, o painel redireciona ao fluxo existente em `/administration/openalex/authors/<gid>?analysis=<id>`, inclusive quando a procedência é outro provedor.

Sugestões vindas das coletas exigem o mesmo trabalho identificado e nome normalizado exato; são evidências a revisar, sem vinculação automática de homônimos. A tela nativa permite consultar perfil conhecido ou buscar nome/instituição, selecionar ocorrências e preparar uma prévia. Confira identidade, posições e comparação antes/depois e confirme explicitamente a aplicação. O fluxo nativo mantém seu trabalho `orcid_apply`, backup e atualização do índice nas etapas próprias. Esta entrega não alterou esse protocolo de revisão e não executou escrita nativa no ensaio ORCID documentado abaixo.

## ORCID de autor recuperado, antes da importação

1. Abra a ocorrência recuperada em `/administration/povoamento/authors/<key>?analysis=<id>` e confira fonte, lote e revisão de origem.
2. Se ainda não houver revisão, use **Preparar revisão deste lote**. Depois atualize o retrato integrado para que a ocorrência tenha uma origem revisável.
3. Confira o ORCID declarado pela fonte ou use **Consultar ORCID** para perfil conhecido/nome/instituição. Abra o perfil oficial e examine a identidade. A API usa `ARGILOTECA_ORCID_READ_PUBLIC_TOKEN`; esse token não estava configurado na validação local. O painel oferece busca no site oficial e erro acionável quando a consulta exige autorização. Não há evidência de consulta nova bem-sucedida à API nesta entrega.
4. Use **Preparar prévia deste vínculo**. A prévia compara a lista de autores antes/depois e mostra evidência e procedência. O identificador já declarado pode aparecer igual nos dois lados: a nova revisão preserva essa associação, sem alegar descoberta de uma identidade nova.
5. Revise, preencha a nota se necessário, marque a confirmação e use **Criar revisão com ORCID**. A ação exige hash do plano, integridade do retrato e da revisão de origem, autor/posição compatíveis e o mesmo administrador. Uma origem alterada exige nova preparação.
6. A confirmação cria outro trabalho de revisão do mesmo provedor, preserva a revisão anterior e as demais correções. Não edita a coleta bruta ou registros nativos. Importação e publicação continuam nos fluxos próprios do provedor; abra a nova revisão antes dessas etapas.

Rotas operacionais desse fluxo: `POST /authors/<key>/search`, `POST /authors/<key>/preview`, `GET /jobs/<job_id>` e `POST /jobs/<job_id>/apply`, sob `/administration/povoamento`. Use os formulários autenticados, que transportam `analysis`, evidência, CSRF e hash do plano.

O ensaio verificado usou o ORCID `0000-0002-4453-9564`, já declarado por um autor PANGAEA. A prévia `53214c41856647d082f7eef2fd858441` gerou a revisão `e820f3531bf642d9b0af3f8f60264bb9`, preservando a origem `08c5cbcd1ab74294b75e292493356ba9`. `verified-orcid-review.json` registra origem inalterada, ausência de escritas nativas, idempotência e SHA do plano. Esse ensaio usa outro retrato (`9c1b20dd984e432e9338b58041a6c7bc`), anterior ao retrato final da interface; não confundir seus IDs.

## PDFs, qualidade e bibliometria

| Ferramenta | Operação e limite |
| --- | --- |
| [PDFs OAI](https://127.0.0.1:5101/administration/repositories/pdfs/?ln=pt) | Consultar staging e abrir trabalhos/arquivos. Nas revisões OAI, a ação de PDFs selecionados prepara o download; não equivale a anexar arquivos ao acervo. |
| [Classificação](https://127.0.0.1:5101/administration/openalex/classification/?ln=pt) | Atualizar a verificação e revisar a prévia antes de aplicar alterações. |
| [Duplicados](https://127.0.0.1:5101/administration/openalex/duplicates/?ln=pt) | Atualizar a verificação, abrir grupos e usar as etapas próprias de revisão/consolidação. |
| [Dados do Acervo](https://127.0.0.1:5101/administration/openalex/enrichment/?ln=pt) | Coletar e revisar complementos no fluxo existente. |
| [Citações e bibliometria OpenAlex](https://127.0.0.1:5101/administration/openalex/statistics/?ln=pt&scope=openalex) | Métricas do recorte OpenAlex publicado. `scope=openalex` mantém a tela bibliométrica; sem esse recorte, a entrada estatística antiga redireciona à visão integrada quando habilitada. |

As últimas execuções exibidas na entrega eram classificação com 15 pendentes em 23/10/2026 e duplicados com 0 grupos em 24/10/2026, com seus próprios horários UTC na interface. Não representam nova avaliação feita em 31/10 nem certificação de qualidade do acervo. Atualize cada ferramenta antes de tomar decisões. As citações, periódicos e demais medidas bibliométricas continuam restritas ao OpenAlex; não foram extrapoladas para PANGAEA, Mendeley ou OAI.

## Retrato final e limites conhecidos

ID: `8ed0acecb42b43ddabd3966ad54a7e85`; preparação: `2026-10-31T14:37:35.852732+00:00`; SHA-256 do SQLite: `f76ef2b9024d630d798f6013fdb7cf802700f2a75e5bcd3736f4402ce2410b65`.

| Contagem global | Valor |
| --- | ---: |
| Publicados | 6.449 |
| Somente rascunhos | 29 |
| Publicados com edição em rascunho, já contados nos publicados | 7 |
| Identidades recuperadas | 1.671 |
| Total de registros/identidades | 8.149 |
| Ocorrências de autoria pessoal | 23.319 |
| Ocorrências com ORCID válido | 66 |
| Ocorrências sem ORCID | 23.253 |
| ORCIDs distintos | 8 |
| Conteúdos PDF distintos no staging OAI | 1 |

Há 12.715 grupos de nomes; esse agrupamento também não mede pessoas únicas. O valor 19.421 em `result.creator_occurrences` pertence à estrutura estatística nativa existente, enquanto a medida integrada é `summary.authors = 23.319`; não trocar seus grãos.

| Fonte | Lotes aceitos | Observações | Vínculos a registros/identidades |
| --- | ---: | ---: | ---: |
| OpenAlex | 7 | 11.531 | 7.304 |
| PANGAEA | 3 | 3 | 2 |
| Mendeley Data | 3 | 11 | 12 |
| LUME UFRGS | 2 | 7 | 6 |
| UFSC | 0 | 0 | 0 |
| Sem fonte identificada | 0 | 0 | 827 |

Os 15 lotes aceitos somam 11.552 observações. As colunas de vínculos a registros não são somáveis, e vínculos nativos podem existir sem observação aceita no retrato atual. “Lote aceito” significa integridade local verificada; não significa cobertura completa do catálogo remoto.

Os dois lotes LUME preservam `coverage.complete=false`: um catálogo parcial com 10 páginas/1.000 observados e outro com 20 páginas/2.000 observados, cada qual com 3 exclusões de registros apagados. Cursor, escopo e datas de coleta ficam nas informações de cobertura do lote. Não apresentar essas coletas como censo completo do LUME.

Três alertas permanecem no retrato:

- OpenAlex `v59_20261023_integracao_sintetica`: fixture ausente, sem arquivo de entrada.
- Mendeley `men_e3921e24bca04df0bf71190dfe5efb7d`: fixture sintética excluída por `ARGILOTECA_POPULATION_EXCLUDED_LOTS` no `invenio.cfg` local; arquivo e histórico preservados.
- OAI `oai_6dbd47728fb14031b89b543379ec239e`: o JSON registra “Arquivo ausente ou acima do limite.” O acesso externo da UFSC estava bloqueado nesta sessão; a ausência de observações UFSC não comprova coleta bem-sucedida sem resultados.

As validações anteriores `f39295a7c76e4bcebd72295397d1d126` e `c74ef3efb6ba4cf88b7e34eb9e514d6e` foram marcadas como falhas/superadas; seus arquivos foram preservados. Não usá-las como evidência do estado final.

## Ativação e desativação local

`ARGILOTECA_POPULATION_ENABLED` usa como padrão a detecção de `SITE_UI_URL` em loopback (`localhost`, `127.0.0.1` ou `::1`). Fora desse contexto, permanece desabilitado por padrão. Uma variável de ambiente com o mesmo nome só habilita pelo valor `true`; configuração explícita da aplicação tem precedência.

Para retirar a extensão da instância local, configure no `argiloteca-rdm14-hml/invenio.cfg`:

```python
ARGILOTECA_POPULATION_ENABLED = False
```

Depois recarregue os serviços locais que carregam essa configuração, conforme o procedimento habitual da instância. Isso desregistra as rotas na próxima inicialização e retira a navegação integrada; preserva journal, SQLite, revisões e arquivos de origem. Não desfaz alterações anteriormente confirmadas nos fluxos nativos. Mantenha a exclusão da fixture enquanto ela estiver presente. Este guia descreve a desativação; nenhum rollback foi executado durante a documentação.

## Evidências e alcance da revisão

Todos os caminhos abaixo partem da raiz do projeto:

- `output/population-admin-20261031/verified-interface.json`: retrato final, contagens, fontes, lotes, alertas, PDF e ausência de token ORCID.
- `output/population-admin-20261031/verified-orcid-review.json`: ensaio real de revisão PANGAEA, integridade e ausência de escrita nativa.
- `output/population-admin-20261031/source-manifest.json`: hashes de 24 arquivos de implementação/configuração/verificação, retrato final, snapshots superados e fixture excluída. Os 24 hashes foram conferidos sem divergência nesta documentação.
- `output/population-admin-20261031/unit-tests.log`, `openalex-regression.log` e `providers-regression.log`: 23 + 156 + 35 + 27 + 16 = **257 testes distintos aprovados**. A documentação consultou os registros e não reexecutou os testes.
- `output/population-admin-20261031/browser-captures.log` e `.impeccable/review/population-integrated/{desktop,mobile}-*.png`: oito cenários com HTTP 200 e largura do documento igual a 1440/390 px. Capturas finais posteriores ao ajuste do shell e reinício local; CSS `?v=20261031-final-2`.
- `.impeccable/review/population-integrated/finish-review.md`: revisão fresca com disposição **ship somente local** após resolução do P2 de oclusão pelo mascote. O verdict pass se limitou a essa resolução nas oito capturas.
- `output/population-admin-20261031/detector.json` e `detector.log`: execução única com resultado `[]` e avisos de resolução CSS/Jinja. Precede os ajustes móveis e do shell, sem representar varredura completa do CSS final.
- `.impeccable/surfaces/population-integrated.md`: contrato e registro de evidência desta superfície.

A revisão visual não certifica ciência, segurança ou persistência e não comprovou visualmente estados vazios, erro, carregamento, foco por teclado, contraste medido, inglês ou outros tamanhos de tela. Cookies do navegador dedicado e arquivos temporários de estado foram removidos ao encerrar a verificação. Não há novo raster a prover; o mascote aprovado é herdado. `DESIGN.md` e `.impeccable/design.json` estavam ausentes e permaneceram ausentes, sem criação ou reparo global nesta extensão.
