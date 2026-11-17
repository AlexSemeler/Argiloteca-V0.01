# Catálogo e mapa como módulo Invenio — homologação, 21/10/2026

## Resultado e arquitetura

Implementação integrada à extensão `argiloteca`, no mesmo blueprint científico,
permissão administrativa e shell usados no Painel DRX. Não há outro banco ou
servidor OAI. Runtime confirmado: Invenio App RDM 14.0.4, Administration 6.1.1 e
OAIServer 5.1.1. O diagnóstico permitido está em
`output/catalog-map-20261021/runtime.json`, na raiz do workspace.

- `/administration/mineral-catalog/`: buscar e adicionar termos; abrir editor.
- `/administration/mineral-catalog/<pid>`: nomes PT/EN, nome científico, grupo,
  classe, fórmula, sinônimos, descrições, fonte, procedência e retirada editorial.
  Salvar rascunho mantém a versão pública; publicar usa o ciclo nativo do Invenio.
- `/administration/mineral-map/`: localizar registros e corrigir coordenadas no
  campo canônico da amostra ou do mineral. Também permite abrir um registro pelo
  PID para acrescentar coordenadas e acessar o depósito científico completo.
- Os dois módulos aparecem na navegação administrativa e têm atalhos nas páginas
  públicas somente para administradores.

Os 81 termos anteriormente públicos foram migrados idempotentemente como registros
nativos com arquivos desativados. `rdm_records_metadata`/`rdm_drafts_metadata`, JSONB,
são a fonte canônica. Rascunhos, PIDs, revisões, permissões, publicação e indexação
continuam nativos. O identificador do termo é permanente e único, inclusive para
escritas pela API nativa, com serialização transacional por slug. Essas escritas
exigem `administration-access`; o processo de importação usa identidade de sistema. Os 46 campos
legados foram preservados; o campo `arg:termo_catalogo` é aditivo.

O serviço público do mapa lê somente registros SQL publicados com metadados
públicos. Snapshots e projeções de busca não substituem os dados canônicos nesse
runtime. Registros do catálogo não geram pontos. A atualização de coordenadas
segue a manutenção estreita já usada nos vínculos DRX: autorização nativa, lock da
linha, revisão esperada, alteração apenas de coordenadas, `RecordCommitOp`, commit
e indexação com refresh. Não republica nem copia os arquivos históricos. Um
rascunho aberto bloqueia essa manutenção para preservar a edição pendente.

## Contrato e interoperabilidade

| Conteúdo | Destino canônico | XML no namespace Argiloteca v1 |
| --- | --- | --- |
| Unidade de descrição | Um registro por termo autorizado; não é ocorrência amostral | `argiloteca/termo_catalogo` |
| Identificador permanente | `custom_fields.arg:termo_catalogo.slug` | `termo_catalogo/slug` |
| Nomes PT, EN e científico | `nome_pt`, `nome_en`, `nome_cientifico_padronizado` | Elementos homônimos obrigatórios |
| Estado editorial | `situacao`: ativo ou retirado | `termo_catalogo/situacao` |
| Grupo, estrutura, fórmula e descrições | Propriedades explícitas do termo | Elementos homônimos opcionais |
| Sinônimos | Lista de strings | `termo_catalogo/sinonimos/item` |
| Referência e procedência | `external_uri`, `observacao_proveniencia` | Elementos homônimos |
| Fontes, créditos, licenças e conteúdo anterior | Objeto estruturado `enriquecimento` | Elementos `property/item` tipados, não JSON em texto |
| Integridade da entrada migrada | `source_sha256`, SHA-256 do perfil público serializado canonicamente | `termo_catalogo/source_sha256` |
| Título, responsável editorial e data | `metadata` nativo; Argiloteca/CPAA como responsável pelo registro terminológico | `metadata`; crosswalk nativo DC |
| Coordenadas | Campos existentes `arg:amostras[*]`, `arg:argilominerais[*]` ou campos escalares legados | Bloco científico ou representação legada existente |

O schema aditivo é `scientific/schemas/arg_termo_catalogo.schema.json`; ele não
substitui nem altera os 14 modelos originais. Nomes obrigatórios não aceitam vazio,
slug tem formato limitado e situação é enumerada. Coordenadas devem ser finitas,
latitude −90 a 90 e longitude −180 a 180. Nenhuma conversão de datum ou confirmação
mineralógica é inferida.

`enriquecimento` preserva o perfil público anterior inteiro, inclusive conteúdo
estruturado das fontes; o formulário administrativo simplificado edita os campos
canônicos acima. Edições posteriores desses campos prevalecem sobre o instantâneo.
O instantâneo não é sobrescrito por nova importação. Créditos e licenças das fontes
continuam preservados; nenhuma licença de reutilização foi inventada para os novos
registros.

O novo campo completo não recebe mapping dinâmico: `enabled:false` no índice.
`arg:indice_cientifico_v1.catalog_slug` e `catalog_status` são projeções keyword para
consulta e seleção OAI. A projeção não substitui o JSON SQL na exportação.

Formato OAI preservado: `metadataPrefix=argiloteca`. Conjunto adicionado:
`set=argiloteca:catalogo`. Exemplo local:

`https://127.0.0.1:5101/oai2d?verb=ListRecords&metadataPrefix=argiloteca&set=argiloteca%3Acatalogo`

O XSD anunciado continua em
`https://127.0.0.1:5101/schemas/argiloteca/v1/argiloteca.xsd`; a cópia gerada está em
`scientific/xsd/argiloteca-v1.xsd`. `oai_dc` e os outros formatos não foram
substituídos. DC mantém título, responsável, data e assuntos pelo crosswalk nativo;
não preserva todos os campos mineralógicos. O XML Argiloteca preserva o contrato
estruturado. Retirar um termo do catálogo marca sua situação e mantém seu registro
coletável; isso não equivale a exclusão nativa ou tombstone.

## Validação comprovada

Evidências locais em `output/catalog-map-20261021/` na raiz do workspace:

| Requisito | Evidência e resultado |
| --- | --- |
| Banco e procedência | 81 registros e 81 hashes de instantâneos conferidos; leitura SQL independente da indexação |
| Curadoria nativa | Três telas HTTP 200 com administrador; acesso anônimo 403; escrita sem CSRF 400 |
| Rascunho e publicação | Rascunho persistido não altera catálogo público; formulário antigo recebe 409; publicação mantém conteúdo e avança `updated` |
| Integridade da API | Identificador duplicado rejeitado também pela API nativa |
| Coordenadas | POST no registro `yhz0x-d0h67`, amostra 0, com os mesmos valores; metadados não relacionados preservados, revisão/data avançadas |
| OAI de catálogo | 81 registros, 9 páginas, sem omissões ou duplicações; envelope oficial, XSD e valores por XPath comparados ao banco |
| OAI misto sem set | 1.308 registros, 131 páginas, todos validados; IDs e títulos confrontados com os registros SQL publicados e públicos |
| Incremental | Atualização de coordenadas aparece em `from` igual ao instante persistido; datestamp de GetRecord coincide até segundos |
| Formatos e leitura | Identify, ListMetadataFormats, GetRecord e ListIdentifiers validados; `oai_dc` respondeu pelo serializer nativo |
| Regressão | 5 testes Python do contrato/coordenadas/XML/projeção; 7 testes JS existentes do catálogo |
| Interface | Inspeção de HTML real renderizado, desktop 1280 px e móvel 375 px; sem overflow horizontal, campos ≥44 px e navegação móvel nativa |

A coleta HTTPS utilizou a CA local configurada, sem desabilitar verificação TLS.
A inspeção visual usou snapshots sanitizados do HTML real, CSS/fontes locais e o
script nativo de navegação. O navegador integrado não confiou no certificado local;
não foi contornado seu aviso. O detector Impeccable não encontrou ocorrências nos
alvos, mas não resolveu os links Jinja para CSS; sua cobertura de cores é parcial.

A coleta mista foi confrontada com o conjunto publicado e público do banco,
excluindo os registros já excluídos. Não foi executada uma nova exclusão de registro
nem uma transição real para acesso restrito durante estes testes. O teste de
coordenadas manteve os valores científicos originais.

## Ativação, recuperação e limites

No Python da aplicação: `python -m argiloteca.scientific.catalog_install`.
O comando instala somente mappings aditivos, importa termos ausentes, preserva
termos/rascunhos existentes, recupera indexação pendente dos publicados e cria o
conjunto OAI se ainda não existir. Não recria tabelas nativas nem reindexa o acervo
inteiro. Nesta execução, uma queda do OpenSearch interrompeu a importação; a
retomada completou os 81 termos sem duplicação. Na regressão JS, corrigiu-se também uma dependência preexistente de `window` nos
agregadores exportados: o fallback de tradução agora funciona sem navegador.
Avisos de índices estatísticos
inexistentes já presentes no runtime não bloquearam os testes.

Após mudanças de Python, reiniciar UI/API e processos de trabalho da composição
`docker-compose.full.yml` + `docker-compose.migrated.yml`. Os volumes locais de
`scientific/`, `mineralogia.py`, `views.py`, templates e CSS já constavam da
composição. Não foi necessário reconstruir a imagem ou atualizar o Invenio.

Para retirar editorialmente, usar a situação Retirado e publicar. Para recuperar
uma edição, reutilizar o histórico/revisão nativo ou restaurar o conteúdo preservado
no instantâneo em novo rascunho; a importação não sobrescreve curadoria. Não apagar
linhas SQL para desfazer a migração, pois PIDs e histórico são nativos.

**Limite externo:** o namespace, o identificador OAI e o XSD ainda são de homologação
local (`127.0.0.1`/`hml.argiloteca.invalid`). A coleta externa em produção exige
publicação e validação sob domínio controlado. Os resultados acima comprovam a
homologação local, não a disponibilidade pública externa.
