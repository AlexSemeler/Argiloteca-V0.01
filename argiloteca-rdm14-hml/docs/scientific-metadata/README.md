# Extensão científica Argiloteca — homologação

Implementação experimental `1.0.0-hml.1`, aplicada em 18/10/2026 ao InvenioRDM 14.0.4 da homologação local. O percurso **JSON → validação → PostgreSQL independente → publicação → OpenSearch → XML → OAI-PMH** foi executado. Não constitui aprovação científica do perfil nem implantação em produção.

## Usar

- Formulário autenticado: <https://127.0.0.1:5101/scientific/deposit>
- Busca e facetas: <https://127.0.0.1:5101/scientific/search>
- Apresentação pública: `/scientific/records/IDENTIFICADOR`; respeita as permissões nativas.
- Exportação: `/scientific/records/IDENTIFICADOR/export` e `/records/IDENTIFICADOR/export/argiloteca`.
- OAI-PMH: <https://127.0.0.1:5101/oai2d?verb=ListMetadataFormats>, prefixo `argiloteca`.
- XSD: <https://127.0.0.1:5101/schemas/argiloteca/v1/argiloteca.xsd>.
- Modelos: `/scientific/models`; validação individual autenticada: `POST /scientific/validate/ARQUIVO.schema.json`.

O menu possui **Depósito científico / Scientific deposit**. O depósito nativo continua disponível e oferece um link para o editor científico. O seletor inglês/português e os catálogos existentes foram conservados.

## Contrato e decisões de homologação

Os 14 JSON Schemas originais estão em `argiloteca_custom/argiloteca/scientific/schemas/`, preservados byte a byte. `field-mapping.json` descreve **302 propriedades declaradas**, inclusive filhos, itens, referências, destinos JSON/XML, unidades declaradas e obrigatoriedade. O gerador está em `tests/scientific/contract_inventory.py`. `$id` identifica o schema; não é prova de endereço público.

| Modelo | Destino canônico |
| --- | --- |
| payload_publicacao | `metadata`, `access`, `files` nativos e blocos `custom_fields`; esquema nativo mantido |
| pesquisa_campo | `arg:pesquisas_campo[]` |
| amostra | `arg:amostras[]` |
| coordenada, localidade, deposito | objetos referenciados em amostras/argilominerais |
| analise | `arg:analises[]` |
| metodo_analitico | objeto referenciado em análises |
| geoquimica | `arg:composicao_quimica_global` |
| argilomineral | `arg:argilominerais[]` |
| publicacao | `arg:publicacoes_relacionadas[]` |
| pacote_analitico | `arg:pacotes_analiticos[]` |
| drx | item tipado de pacote analítico, quando satisfaz o schema DRX |
| referencia_drx_webmineral | `arg:referencias_drx_webmineral[]`, auxiliar e não confirmatória |

A unidade é o registro InvenioRDM, com blocos científicos opcionais e referências locais. Não foram criadas tabelas de entidades científicas independentes. Não se impõem campanhas ou amostras a artigos legados. Os 46 campos anteriores permanecem; quatro campos adicionais totalizam 50 definições registradas: versão do perfil, projeção de busca, pacotes e referências WebMineral.

A presença de `arg:perfil_versao = 1.0.0-hml.1` ativa validação científica. Sem esse campo, vale a compatibilidade anterior. Não houve conversão automática dos registros legados. Rascunhos conservam entradas incompletas/inválidas e retornam `errors`; a publicação chama a validação estrita do serviço nativo. O envelope bibliográfico é tratado pelos schemas nativos Invenio, mais rigorosos em vários pontos que o payload fornecido; não foi substituído o `$schema` nativo.

Além das regras dos arquivos, foram reaproveitadas as relações já presentes no código local `argiloteca_custom/traceability.py`: unicidade de campanha/amostra/análise e referências locais a essas entidades. Essas regras são do perfil local, não inferências do padrão JSON Schema. Os demais condicionais permanecem os fornecidos. Os 14 modelos podem ser validados separadamente pela rota autenticada.

### Limites semânticos preservados

- Os modelos permitem propriedades adicionais. Elas ficam no banco e são preservadas ao editar. Propriedades não declaradas em objetos científicos nomeados não entram no XML público nem na projeção de busca. Objetos explicitamente livres, como `provenance`, e itens genéricos de pacotes têm representação XML estruturada `property/item`, com tipos; podem conter `null`, `false`, listas e objetos.
- O `anyOf` de `pacote_analitico.items` aceita DRX **ou qualquer objeto**. Um objeto genérico não comprova validação DRX. A interface oferece as duas estruturas; a exportação distingue `<drx>` de `<generic>`.
- Alternativas `anyOf` de nomes/localidade/publicação representam presença de propriedades conforme os arquivos. Não foram inventadas cardinalidades ou validações científicas adicionais.
- Unidades não declaradas nos arquivos não foram inferidas nem convertidas. IDs, vocabulários e nomes científicos não são traduzidos automaticamente.
- Valores JSON numéricos seguem o transporte numérico nativo e o JavaScript. Testou-se a preservação de `12.3456789012345` e coordenadas com casas decimais; precisão decimal arbitrária acima da capacidade do transporte não é garantida.

## Persistência, busca e vocabulários

Campos permanecem nos JSONB nativos `rdm_drafts_metadata.json` e `rdm_records_metadata.json`; não há alteração DDL/Alembic. As subclasses mantêm os componentes, permissões, arquivos, PIDs e ciclos nativos. O `DictField` padrão eliminava `null` e listas vazias: o perfil explícito usa um campo que os conserva, sem mudar a limpeza dos legados. Uma edição científica mescla apenas seus próprios campos e exige remoção explícita, preservando os demais.

`arg:indice_cientifico_v1` existe somente no documento de busca. É removido na carga e não aparece no JSON canônico do banco. Seus grupos `samples`, `analyses`, `minerals` e `chemistry` são `nested`, com tipos explícitos. Filtros do mesmo grupo consultam o mesmo item: **Kaolinite + latitude 1** não corresponde a Kaolinite em latitude 0 e Illite em latitude 1. Há filtros por perfil, campanha, amostra, método/laboratório e mineral/amostra/latitude, com facetas por campanha, método e mineral.

Para registros com perfil, somente essa projeção científica é indexada. Os blocos completos são lidos do PostgreSQL para edição, detalhe e XML. Isso evita explosão de campos dinâmicos e conflitos com tipos históricos. A busca continua incluindo metadados bibliográficos nativos. Listagens de busca fornecem resumo; leitura do registro fornece todos os blocos.

O instalador inicializa de modo aditivo os índices atuais de publicados, rascunhos e percolação OAI e verifica os tipos. Não executa `custom-fields init` em todos os campos: há um conflito preexistente `float/double` em campos antigos. Um mapeamento transitório do primeiro rascunho de teste foi preservado; a projeção definitiva usa o nome versionado. O instalador pode rodar novamente sem modificar conteúdo.

Vocabulários nativos idempotentes: `argprofiles` (uma versão) e `argmethods` (dez tipos fornecidos pelo modelo). Rótulos inglês/português são separados dos IDs. O campo livre `metodo` permanece compatível; o enum de `metodo_analitico.tipo` não foi ampliado.

## XML e OAI-PMH

O XSD versionado está em `argiloteca_custom/argiloteca/scientific/xsd/argiloteca-v1.xsd`. O gerador, exportador nativo e adaptador OAI compartilham a definição do perfil. XML contém elementos tipados, listas `item`, booleanos, decimais e `xsi:nil`; não contém JSON escapado como substituto do modelo. Cada XML gerado é validado no XSD antes da resposta.

O namespace e a URL XSD são **locais à homologação**. Um domínio público controlado ainda precisa ser definido/publicado e testado de fora do ambiente. Não anunciar este perfil como padrão científico aprovado ou coletável externamente antes dessa etapa.

Todos os registros públicos elegíveis para OAI podem usar `argiloteca`: núcleo bibliográfico e blocos opcionais. Legados recebem `profiled=false` e os campos legados reconhecidos em estrutura própria. Isso mantém coerência entre `ListMetadataFormats`, `GetRecord` e `ListRecords` numa coleção mista. Os oito formatos anteriores, incluindo `oai_dc`, permanecem configurados.

A integração usa hooks próprios, sem editar pacotes do Invenio:

- Nome OAI concreto, porque `lxml` não aceita o título de interface em `LazyString`.
- Consulta de pertencimento a sets no índice publicado para `GetRecord`; evita inferir mapeamentos a partir do payload científico completo. Listagens nativas continuam usando a percolação, com a projeção explicitamente mapeada.
- Formato desconhecido retorna `cannotDisseminateFormat` pelo protocolo, em vez do `badArgument` genérico dessa versão nativa.
- O adaptador lê o JSON canônico e verifica permissões tanto em `GetRecord` quanto em `ListRecords`; a projeção do índice não substitui dados científicos.

`Identify` anuncia granularidade UTC de segundos e **`deletedRecord=no`**. Mudanças científicas republicadas atualizam o datestamp nativo; foi testada janela com `from=until` no segundo correspondente. Retirada por restrição e remoção lógica deixam de ser acessíveis anonimamente. Como não há tombstones OAI persistentes, coletores precisam de reconciliação completa periódica para remover itens retirados. Não se promete histórico de exclusões pela coleta incremental.

Uma alteração futura no crosswalk/formato, sem mudança nos registros, exige nova versão documentada e coleta completa. Reindexar não atualiza datestamps; não se deve alterar datas científicas/bibliográficas apenas para provocar coleta.

## Ativação e reprodução

A partir de `argiloteca-rdm14-hml/`, com o Compose migrado já configurado:

```bash
./scripts/init-scientific-metadata
./scripts/test-scientific-metadata
./scripts/verify-scientific-evidence
```

O primeiro comando altera apenas mapeamentos adicionais e os dois vocabulários próprios; os dois seguintes são offline e não conectam ao banco. Os comandos usam o runtime Docker, sem instalação global de Node/Python.

A reindexação limitada aos índices RDM atuais é reproduzível com:

```bash
docker exec -i argiloteca-rdm14-hml-web-ui-1 python - < tests/scientific/reindex.py
```

O script compara hashes do JSON e timestamps ao indexar; não faz migração de conteúdo nem commit de registros. Na execução registrada, foram indexados 2.164 publicados e 54 rascunhos, mantendo seus conteúdos.

Para gerar uma nova evidência, execute na ordem: integração; preparação do set/arquivo; coleta HTTPS; verificação offline; alteração/retirada e sua verificação HTTPS. A coleta guarda uma coleção estável para comparar os valores daquela execução.

Os testes de integração em `tests/scientific/integration.py`, `prepare_harvest.py` e `incremental_withdrawal.py` escrevem **fixtures sintéticas de homologação**, usando serviços nativos. `harvest_http.py` e `check_incremental_http.py` acessam HTTPS real com a CA local. `verify_evidence.py` valida os arquivos coletados offline com o envelope OAI oficial e schemas auxiliares locais. Fontes e hashes dos XSDs auxiliares constam em `tests/scientific/xsd/sources.json`; os originais também foram preservados. A resolução local muda caminhos de importação e elimina a dependência de DTD externo, mantendo as declarações. O XSD oficial OAI não foi alterado.

O Playwright foi executado pela skill local e seu wrapper, com a configuração Chromium de homologação. `tests/scientific/playwright-fill.js` contém a interação de preenchimento, sem credenciais. Login, publicação, edição completa, troca de idioma, depósito nativo e busca foram exercitados no navegador real. A revisão de publicação é conferida pelo helper nativo antes de chamar `publish`, pois o override RDM 32.3 não recebe esse argumento; requisição com revisão obsoleta foi rejeitada com HTTP 409.

As fontes primárias e versões de referência estão em [sources.json](../../../.agents/skills/argiloteca-invenio-metadata/references/sources.json), e as versões observadas em [runtime.json](runtime.json).

Consulte [ACCEPTANCE.md](ACCEPTANCE.md) e [results.json](results.json) para resultados e evidências. Evidências completas ficam em `output/metadata-extension/` na raiz do repositório, ignoradas pelo Git. Backup de banco e credenciais de QA não são documentos públicos nem devem ser versionados.

## Recuperação e estado de implantação

Antes da alteração foram salvos o dump PostgreSQL e os arquivos de configuração/código anteriores; a imagem anterior foi marcada `argiloteca-rdm14-hml:before-metadata-20261018`. A imagem final tem tag `argiloteca-rdm14-hml:metadata-20261018-final` e foi aplicada aos processos web e workers. Contas temporárias de QA foram desativadas, sessões revogadas e credenciais temporárias removidas. Os registros sintéticos de demonstração continuam identificados na homologação. Nenhum commit foi criado.

Rollback de código deve restaurar também as configurações que importam as subclasses científicas. Campos novos no índice são aditivos e podem permanecer sem uso. Restaurar o banco completo é uma operação distinta: deve considerar alterações concorrentes e não ser feito automaticamente. O dump é recuperável, mas não é uma estratégia para sobrescrever trabalho posterior.
