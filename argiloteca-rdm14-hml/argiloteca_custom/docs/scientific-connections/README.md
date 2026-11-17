# Conexões científicas — homologação 21/10/2026

## Uso pela curadoria

Abra **Administração → Conexões científicas** (`/administration/scientific-connections/`). Busque uma publicação ou um conjunto de dados pelo título ou PID nativo. A tela mantém o registro selecionado como origem de cada relação.

1. **Publicação e dados:** busque o registro de destino, confira seu título e escolha a relação **da origem para o destino**. Exemplo: quando os dados complementam um artigo, no artigo escolha destino Conjunto de dados e relação “É complementado por”. Na direção inversa, no conjunto de dados escolha destino Publicação e “Complementa”. Informe uma justificativa pública com seção, tabela, DOI ou outra fonte verificável e confirme o salvamento. Não crie as duas direções manualmente: a navegação inversa é calculada a partir da relação persistida.
2. **DRX:** busque o nome anônimo/identificador do arquivo; inspecione curva, procedência e relatório antes de associar. Mantenha Pendente enquanto a origem não estiver conferida. Confirmado significa vínculo curatorial com o registro, não identificação mineralógica confirmada. Revisões existentes preservam estado e justificativa no formulário. A lista tem páginas de 20 vínculos. Restrição de RAW, candidatos, classificação histórica e acesso permanecem sob o mecanismo DRX existente.
3. **Catálogo:** sugestões vêm dos nomes já declarados. Revise cada destino e sua fonte. A relação `references` identifica o assunto da publicação/dado. Ela não cria ocorrência, coordenadas nem confirmação de fase mineral. O catálogo oferece navegação inversa para os registros relacionados.
4. **Mapa:** mantenha coordenadas no registro que documenta a amostra/resultado. Quando um artigo referencia outro conjunto de dados, conecte os registros e abra o mapa do conjunto. O link filtra pelo PID e usa somente as coordenadas existentes; o editor de coordenadas continua separado.

A conexão salva aparece no registro nativo e em `/scientific/connections/<pid>`. A API de leitura `/scientific/records/<pid>/connections` declara `schema_version: 1`. Destinos e origens sem permissão de leitura não têm título ou justificativa revelados nessa navegação. Registros do catálogo são destinos de referências; sua descrição é editada no módulo do catálogo.

## Contrato e preservação

| Informação | Autoridade | Persistência/exportação |
|---|---|---|
| Autoria, título, data, licença, arquivos, acesso, PIDs e publicação | Serviço nativo InvenioRDM | Preservados pela manutenção de conexões |
| Relação publicação–dados ou referência a termo | `metadata.related_identifiers` | URL canônica do PID, esquema `url`, vocabulário nativo `relation_type`; exportável também em `oai_dc` |
| Justificativa, papel do destino e slug de termo | `arg:conexoes_cientificas` | Lista estruturada validada pelo JSON Schema; XML `conexoes_cientificas/item` e OAI `argiloteca` |
| Vínculo RAW–registro e revisão curatorial | `DRXRecordLink` e eventos existentes | Mesma implementação de revisão/integração DRX e pacote analítico persistido; não copia nem libera RAW |
| Localização | Coordenadas já declaradas no registro/amostra | Fonte canônica SQL do mapa; nenhum ponto é deduzido de citações |

O campo de conexões é opcional, com no máximo 50 destinos únicos, sem autorreferência. O destino precisa ser publicado e público ao criar/alterar uma conexão; os papéis Dados/Publicação precisam corresponder ao tipo nativo. Termos exigem slug ativo e relação `references`. Conexões antigas inalteradas podem ser preservadas/removidas mesmo se um destino deixou de ser público. URLs de relações já publicadas continuam como citações históricas; não se armazena uma cópia do título privado. A justificativa é pública e o formulário explicita esse alcance antes de salvar.

A marca booleana `native_relation_created` registra a propriedade do adaptador sobre a citação nativa. O XML científico omite essa marca. Remover um vínculo apaga somente a citação nativa criada por esse adaptador; citações preexistentes e as demais relações são preservadas. Links inversos são calculados por consulta JSONB ao banco, sem duplicar relações nem atualizar artificialmente o registro de destino.

`ConnectionsIntegrityComponent` protege também criação, atualização de rascunho e publicação pela API nativa. Usuários sem administração não adicionam nem removem conexões; uma edição bibliográfica comum preserva os vínculos omitidos do formulário. A manutenção administrativa usa autorização administrativa completa, CSRF, confirmação explícita, bloqueio de linha e revisão otimista. Rascunhos abertos impedem essa manutenção. Ela avança a revisão/data OAI do registro publicado via operações nativas, sem republicar arquivos históricos. Novos depósitos continuam passando pela publicação nativa.

A instalação acrescentou apenas um mapping `UnindexedObjectCF` aos índices de publicados, rascunhos e percoladores. São 52 campos locais, incluindo os 46 legados. Sem tabelas novas, migração de conteúdo em massa ou reindexação integral. Os 14 modelos científicos originais foram preservados; o schema de conexão é adicional. O XSD v1 recebeu um elemento opcional adicional e continua aceitando os payloads anteriores.

## Verificação comprovada

Evidências em `output/admin-connections-20261021/`, a partir da raiz do repositório.

- **Interface real Firefox:** salva a referência do artigo `cm207-2xw77` ao termo Antigorita `ep84x-c6y30`. Evidência: nome explicitamente declarado no título e em `arg:argilominerais`. A conexão factual foi mantida na homologação. Não foram inventadas associações desse artigo com RAW ou conjuntos de dados.
- **SQL independente:** todos os campos personalizados anteriores, metadados bibliográficos, arquivos, acesso, PIDs, parent e versões preservados. Únicas adições científicas: campo de conexão e citação nativa. Contagem publicada continua 1308. Nenhum rascunho aberto foi criado; tabelas internas podem conservar uma linha histórica de rascunho após a publicação.
- **Índice e leitura pública:** conexão encontrada no índice e nas páginas do registro, do termo e na navegação inversa. Mapa recebe filtro do PID de um conjunto de dados existente. Endpoint DRX existente responde preservando seu contrato.
- **OAI:** `GetRecord` em `argiloteca` com XML tipado válido pelo XSD; `oai_dc` contém a URL do termo em `dc:relation`. `ListRecords` com `from=2026-10-21T13:25:54Z` encontra o registro atualizado. Os XMLs integrais estão nas evidências.
- **Proteções HTTP:** acesso administrativo anônimo negado; formulário com revisão antiga recebe 409; confirmação ausente 422; CSRF ausente 400. Falhas preservam o SQL. Bloqueio por rascunho aberto comprovado em transação revertida.
- **Publicação nativa:** criação de rascunho, publicação e XML com relações para termo e conjunto de dados passaram dentro de uma transação sem commit. Rollback e contagens SQL originais conferidos. Nenhuma publicação de teste ficou no banco ou índice.
- **Regressões:** 15 testes de conexões, 5 de catálogo/coordenadas/XML e 7 testes JS do mapa/catálogo passaram. Capturas desktop e móvel no Firefox. Detector Impeccable sem ocorrências nos três alvos examinados; é análise estática, sem resolver todos os estilos Jinja e sem substituir a inspeção visual.

Os testes transacionais não estabelecem vínculo científico real entre o artigo e o conjunto de dados usado como fixture. A manutenção DRX reutiliza o serviço existente; a execução não reclassificou RAWs nem liberou arquivos restritos. Não foi repetida a coleta integral de 1308 registros nesta alteração: a coleta integral anterior do módulo catálogo/mapa permanece como baseline; aqui foram exercitados GetRecord, coleção incremental, persistência e publicação.

## Ativação e recuperação

Executar no Python da aplicação: `python -m argiloteca.scientific.install` (idempotente, mappings aditivos). Reiniciar UI/API/worker da composição `docker-compose.full.yml` + `docker-compose.migrated.yml`. Nenhuma atualização de versão do Invenio é necessária.

Testes de contrato: copiar `tests/test_scientific_connections.py` para o container e executar com `/opt/invenio/src/.venv/bin/python`. Os scripts de auditoria e da transação nativa estão no diretório de evidências, com os PIDs específicos desta homologação. A comparação SQL usa o snapshot anterior fornecido; não recapture o “antes” após salvar a conexão.

Para desfazer um vínculo, usar **Remover vínculo** na mesma tela. A confirmação e a revisão continuam obrigatórias; não excluir linhas SQL/PIDs. A relação nativa preexistente é preservada quando não pertence ao adaptador. Para corrigir justificativa/relação, buscar o mesmo destino novamente: os valores salvos são preenchidos para revisão.

**Limite externo:** namespace/XSD, URLs canônicas e endpoint OAI ainda pertencem a `127.0.0.1:5101`. Foi comprovada a homologação local; disponibilização a coletores externos exige o domínio e a validação de produção já previstos para o módulo.

## Teste adicional pelo painel: publicação, dados e DRX

Em 21/10/2026, com escolha explícita do usuário por teste temporário e remoção ao final, foi salva pela interface uma referência da tese `4rxma-end93` ao dataset `6r8jn-f6b07`. SQL, índice, navegação nos dois sentidos, mapa de cada registro, GetRecord em `argiloteca` e `oai_dc` e coleta incremental foram comprovados. A relação temporária e a citação nativa foram removidas pelo painel; a limpeza foi conferida nas mesmas camadas. O conjunto de dados permaneceu exatamente igual ao anterior.

O vínculo RAW existente `a0d67e52c9f1e4117e3c1976` foi revisado e salvo com o mesmo estado Pendente e a mesma evidência: revisão 1 → 2. Derivado, hash, classificação e restrição foram preservados; acesso anônimo permanece 404. A navegação publicação → biblioteca RAW → painel DRX mostrou a curva e o retorno à tese como vínculo pendente. Não se confirmou uma procedência científica nem se criou um novo registro para o teste.

A tese terminou na revisão 33; permaneceu a atualização de `generated_at` do pacote DRX e uma lista opcional vazia de conexões. Contagem publicada permanece 1308. Relatório detalhado, instantâneos, scripts, XMLs e capturas: `output/connections-panel-e2e-20261021/README.md`, na raiz do repositório.
