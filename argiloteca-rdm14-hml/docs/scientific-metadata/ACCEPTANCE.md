# Matriz de aceitação — 18/10/2026

`comprovado` significa teste executado no runtime indicado. Evidências referidas abaixo ficam na raiz do repositório em `output/metadata-extension/`, com dados sintéticos explicitamente identificados. A coleta geral contém também registros públicos existentes; não contém rascunhos/restritos. Resultados não atestam aprovação científica.

| Requisito | Implementação | Teste/evidência | Resultado |
| --- | --- | --- | --- |
| 14 modelos e contrato por campo | Registry offline, Draft 2020-12, checker URI explícito, 302 propriedades mapeadas | `unit-tests-final.log`, `field-mapping.json`; casos positivos/negativos e `anyOf` permissivo | comprovado |
| Persistência transacional | Custom fields nos JSONB nativos, valores científicos sem limpeza de nulos | `integration.json`, comparação integral por processo/SQL independente; releitura REST | comprovado |
| Rascunho/publicação | Schema do serviço; erros de rascunho não impedem salvar; publicação estrita | inválido salvo, inválido rejeitado, corrigido publicado; inspeção de `errors` | comprovado |
| Edição/nova versão e outros campos | Componentes nativos e mescla científica restrita | integração e `playwright-full-edit.log`; `arg:usos_descricao` preservado | comprovado |
| Fidelidade de valores | Tipos estruturados, ausência/null/vazio explícitos | código `0001`, `0`, `false`, Unicode, caracteres XML, precisão, listas/objetos; igualdade integral por decodificador XML independente | comprovado |
| Legados/sem DOI | Perfil optativo; núcleo bibliográfico OAI para legados | publicação sem DOI, artigo legado, coleção mista e formato anterior `oai_dc` | comprovado |
| Busca/facetas | Projeção `nested` explícita em publicados/rascunhos/percolador | consulta positiva e falso cruzamento excluído; facetas; `reindex.json` | comprovado |
| Vocabulários | `argprofiles`, `argmethods` nativos | `installation.json`, segunda execução sem campos adicionados | comprovado |
| Formulário/API/visualização | Editor estruturado, resumo público, ponte para depósito nativo | integração autenticada; Playwright cria, salva, reabre, publica, edita todos os blocos e relê API | comprovado |
| Idiomas/mobile | Inglês/português e seletor existente | `playwright-pt-mobile.log`, `playwright-en-search.log`; largura 390 = scrollWidth 390 | comprovado |
| Autenticação/permissões | Login e permissões nativas, CSRF explícito nas rotas do editor | rascunho/restrito negados anonimamente; CSRF ausente rejeitado; arquivo realmente restrito negado | comprovado |
| Descoberta OAI | Nove formatos, namespace e XSD locais consistentes | `Identify`, `ListMetadataFormats`, três tipos de registros e formato desconhecido | comprovado |
| XML/XSD e valores | XML tipado, exportador nativo e adaptador OAI canônico | `oai-validation.json`: envelope oficial e payload; XPath e igualdade integral dos oito blocos | comprovado |
| Paginação | Tokens opacos nativos até o fim | 1.234 registros / 124 páginas sem set; 15 / 2 páginas com set; ListIdentifiers e 11 sets / 2 páginas | comprovado |
| Coleção mista | Formato válido com perfil e legado | GetRecord, ListRecords com/sem set; acesso consistente por item | comprovado |
| Exposição | Publicação/acesso nativos, allowlist de propriedades nomeadas | rascunhos/restritos ausentes da coleta; enriquecimento desconhecido retido no banco e ausente do XML; metadado público com arquivo protegido | comprovado |
| Incremental/retirada | Datestamp nativo UTC; política nativa `deletedRecord=no` | `incremental-http.json`: mudança só científica, `from=until`; restrição e remoção lógica testadas | comprovado |
| Implantação/recuperação | Mapeamentos aditivos, sem DDL/migração de conteúdo; imagem e backup anteriores | inicialização repetida; hashes de reindexação; processos web e workers com a mesma imagem | comprovado |
| Disponibilidade externa do perfil | Rotas e XSD locais entregues | Falta domínio público controlado e coleta de ambiente externo | bloqueado — publicação externa ainda não estabelecida |

## Limites registrados

- Perfil de homologação experimental, com decisões explícitas no README. Os schemas fornecidos continuam permissivos onde originalmente o eram; isso não confirma interpretação mineralógica.
- Precisão decimal arbitrária além do transporte numérico nativo/JavaScript não foi implementada. Os valores discriminantes declarados nos testes sobreviveram.
- OAI sem tombstones persistentes exige reconciliação de coleções após retiradas. Alteração de crosswalk exige estratégia de recoleta completa.
- Há avisos preexistentes de índices estatísticos ausentes (`stats-record-view`, `stats-file-download`); eles não impediram a cadeia científica. Não foram tratados como novos testes aprovados de estatística.
- O repositório já continha grande parte da aplicação sem rastreamento. Não foi usado `git add .` nem criado commit; os arquivos da skill previamente preparados foram preservados.
