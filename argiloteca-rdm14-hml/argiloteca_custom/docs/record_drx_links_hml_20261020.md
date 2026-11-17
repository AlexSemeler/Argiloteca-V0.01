# DRX por registro, vínculos persistidos e exportação científica

Implementação de homologação em 20/10/2026 (execução UTC atravessou 21/10). Exemplo: `4rxma-end93`.

## Resultado e limites científicos

A tela `/analises/<record_id>` agora compartilha a interface de Análises/DRX, a sessão de comparação e o modo expandido. O painel contextual usa as associações atuais, em vez de recorrer ao manifesto estático de maio quando uma consulta falha. A seleção explícita de um registro carrega um RAW acessível se a comparação estiver vazia; uma seleção já existente é preservada.

Foram reconciliadas 635 identidades de arquivo do pacote antigo com o acervo anônimo, por SHA-256 de origem e correspondência restrita ao derivado. Isso demonstra identidade de arquivo, não confirma que todas as amostras pertencem cientificamente ao registro. Os 635 vínculos ficaram **pendentes** e os derivados continuaram **restritos**. Não há trio N/G/C completo e confirmado nesse subconjunto; nenhum agrupamento foi inventado a partir de nomes semelhantes.

Os 635 arquivos têm revisão de processamento separada `argiloteca-record-drx-v3.1-20261020`: 539 avaliações com classificador primário compatível com Cu e 635 avaliações do piloto estrutural AMCSD/COD. Para outras radiações, o primário Cu não é aplicado. Posições e intensidades são mantidas; espaçamentos d são calculados com λ declarada. A revisão preliminar v3 foi conservada no histórico e substituída na seleção corrente por v3.1, que explicita essa regra também na tabela de picos. Não houve alteração dos resultados históricos congelados nem da identificação curada nos metadados legados.

Resultados automáticos são candidatos, não confirmação, probabilidade ou porcentagem mineralógica. O piloto usa o subconjunto de referências já instalado; não equivale à cobertura integral de AMCSD ou COD Inorganics.

O usuário autorizou restringir o arquivo nativo `raw.rar.zip`: somente `access.files` passou a `restricted`, mantendo `access.record=public`, os objetos de arquivo, PIDs, metadados bibliográficos e demais campos científicos existentes. Nenhum serviço de publicação foi invocado.

## Fontes de verdade

- `scientific/drx_links.py`: modelos SQL, controle de revisão, auditoria e projeção pública por allowlist.
- `scientific/drx_reprocess.py`: revisões calculadas a partir do derivado verificado por hash.
- `scientific/drx_similarity.py`: recuperação de curvas medidas, separada da identificação e da curadoria.
- `scientific/drx_link_views.py`: autorização administrativa, consultas de vínculos e curvas do workbench.
- `scientific/xml.py` e `scientific/schemas/arg_drx.schema.json`: XML/XSD tipado, incluindo pacote válido em registro legado sem migração de perfil.
- `services/analytical_packages.py`: contratos legados preservados; rotas de registros com vínculos persistidos passam pela camada canônica antes desse fallback.

Tabelas aditivas: `argiloteca_drx_record_link`, `argiloteca_drx_link_event`, `argiloteca_drx_analysis_revision`. Associação única por PID de versão do registro/RAW, vinculada ao SHA-256 do derivado. Revisões de classificação são únicas por RAW/hash/engine. Não se escreve no índice histórico de arquivos nem nos originais. A migração `install_tables()` cria somente essas três tabelas, de forma idempotente.

A manutenção de metadados é específica e autorizada: exige permissão nativa de edição, bloqueia a linha SQL, relê o registro, preserva campos alheios, valida o pacote e usa `record.commit()` com sinais/revisão nativos. Vínculo, auditoria e metadados são confirmados na mesma transação; a indexação ocorre após commit. Uma falha de indexação requer reindexação do registro, sem refazer a curadoria ou publicar. Rascunhos não são modificados automaticamente. O formulário se destina a registros existentes; preparar/publicar um rascunho continua sendo o fluxo nativo separado.

## Interface e acesso

- Administração → **Registros e dados DRX**: busca bidirecional por PID/RAW, estados pendente/confirmado/removido, evidência obrigatória e controle de concorrência. Remoção é reversível e auditada.
- Detalhe do RAW e Análises do registro dão acesso à revisão. Vincular/confirmar não libera um arquivo restrito.
- Comparação de temporários mostra RAWs medidos similares e permite adicioná-los à seleção. Aliases do mesmo RAW do acervo são deduplicados sem remover o temporário.
- **Inspeção dos dados → Registros relacionados** consulta novamente o banco e mostra títulos, PIDs, links e arquivos associados ao RAW ativo e aos RAWs comparados. Vínculos pendentes são visíveis somente na administração; autorização do registro é verificada também para RAWs públicos.
- Rotas privadas usam `private, no-store` e variam por cookie. Manifestações estáticas substituídas não ficam acessíveis anonimamente. Nenhuma sessão do Firefox é copiada para testes automatizados.

Rotas novas:

- `GET /scientific/drx/records/<pid>`: pacote com acesso por identidade.
- `GET /scientific/drx/raws/<raw_id>/download` e `/links`.
- `GET /scientific/drx/related-records?raw_ids=<id,...>`: até 20 IDs anônimos; sem nomes de origem.
- `GET|POST /administration/drx-links/`: administração nativa + CSRF em escrita.
- `GET /api/argiloteca/drx/difratogramas/linked:<raw_id>`: curva do acervo verificada por hash.

Os caminhos antigos `/api/argiloteca/analises/<pid>` e aliases continuam válidos. O suporte standalone Flask/contratos legados fica separado da integração SQL, que exige a extensão nativa de registros. A homologação real usa e testa essa extensão.

## Comparação entre curvas medidas

A identidade exata exige SHA-256 igual. Coincidência de nome não é identidade. A busca de semelhantes usa cosseno em grade de q=1/d com 4096 posições entre 0,015 e 0,8 Å⁻¹, subtração do percentil 10 e sobreposição mínima de 60% do intervalo do arquivo consultado. Não há extrapolação, ajuste automático de deslocamento ou radiação presumida nesse recuperador. λ declarada é obrigatória para comparação numérica; a identidade por hash pode ser reconhecida mesmo sem ela.

Por padrão são consultados os RAWs públicos. No contexto de um registro, também podem entrar seus derivados restritos se a identidade tiver acesso administrativo. Similaridade não grava vínculos nem muda identificações. A métrica é exploratória e exige validação mineralógica independente.

## Persistência e OAI-PMH

`arg:pacotes_analiticos` guarda a projeção pública do vínculo na fonte SQL nativa. Arquivos/vínculos restritos ou pendentes geram somente contagens; não exportam nomes, hashes individuais, curvas ou resultados restritos. Arquivos públicos com vínculo confirmado exportam os campos tipados de `arg_drx`: código anônimo, arquivo, SHA-256, formato, preparo, número de pontos, λ (Å), proveniência do eixo, picos (2θ/d/intensidade), candidatos primários e evidências estruturais separadas em modo sombra. A definição DRX ganhou propriedades opcionais aditivas; não houve mudança dos identificadores científicos nem promoção automática dos registros legados ao perfil completo.

O formato `argiloteca` do OAI lê a fonte SQL e valida a carga no XSD anunciado. `record.updated` avança na manutenção e permite coleta incremental. O PID OAI legado do exemplo foi preservado: `oai:oai:invenio-app-rdm.org::4rxma-end93`. Não usar o prefixo de configuração para adivinhar IDs migrados; usar `pids.oai.identifier` ou ListIdentifiers. Namespace/XSD permanecem locais; publicação externa de domínio não faz parte desta entrega.

Mudanças futuras de acesso no catálogo de derivados exigem reconciliar a projeção nativa antes da coleta. Não editar manualmente somente o JSON do índice; associações, hashes e política de acesso devem continuar consistentes.

## Operação e reprodução

**Sempre usar os dois arquivos Compose**. A configuração base isolada aponta para a base de ensaio, não para a base migrada utilizada pela homologação.

```sh
cd argiloteca-rdm14-hml
docker compose -f docker-compose.full.yml -f docker-compose.migrated.yml up -d --no-deps web-ui web-api worker
```

Depois de recriar containers, reiniciar também o `frontend` para atualizar a resolução dos upstreams. As cópias coletadas dos manifestos em `/static/...` redirecionam para a rota que verifica a política atual; não são uma alternativa pública ao controle de acesso. Após criar tabelas e antes de habilitar tráfego, testar fonte SQL, API, acesso anônimo/admin e OAI. A migração pode ser invocada em contexto da aplicação:

```python
from invenio_app.factory import create_ui
from argiloteca.scientific.drx_links import install_tables
app = create_ui()
with app.app_context():
    install_tables()
```

Artefatos desta execução em `output/record-drx-integration-20261020/`; correspondências e renders autenticados ficam exclusivamente em `restricted/`, excluído do Git. O backup do registro antes da manutenção e antes da restrição está no volume privado `data/drx-record-maintenance/20261020/`. Para restaurar, revisar as revisões e restaurar somente os campos autorizados, nunca publicar nem reabrir arquivos automaticamente.

Testes: `tests/test_drx_record_links.py`, limites de upload/temporários e testes administrativos existentes. A verificação nativa adicional testa CSRF, permissão, vínculo salvo/reaberto, conflito de revisão e rollback de toda associação fictícia. Nenhum vínculo de teste deve permanecer. Capturas de renders autenticados servem para layout; não são prova de login real de navegador. O teste do navegador público usa respostas HTTPS reais.

## Evidências finais

- 81 testes aprovados no Python 3.14.7 da homologação, NumPy 2.3.5 e SciPy 1.18.1, incluindo importação real de `scipy.signal.find_peaks`. Um aviso de depreciação nativo preexistente.
- Teste nativo autenticado: 635 vínculos, 635 revisões correntes; gravação/reabertura, CSRF, conflito e rollback de vínculo fictício. Leitura de arquivo restrito pelo fallback legado também recusada antes de chamar o leitor.
- Sessão SQL independente reaberta; sincronização repetida sem nova revisão. Arquivo nativo restrito, registro público e nenhum novo registro publicado.
- HTTPS real: arquivo original/API403, download pela interface redireciona para login, arquivo agregado403 e manifestos substituídos404, incluindo cópias coletadas.
- GetRecord200, carga validada no XSD anunciado e ListRecords incremental contendo o exemplo com datestamp atualizado. Identificador OAI legado preservado.
- Navegador público real: RAW renomeado reconhecido por SHA-256 entre 1.224 arquivos; aliases da referência deduplicados; temporário e duas curvas do acervo mantidos após alternância. Hashes dos vetores e do objeto File iguais antes/depois, modo expandido ativo nas duas telas e cancelamento de Remover todas preservando as três curvas.
- Aba Registros relacionados em 1440/390/320px sem transbordamento. Layout autenticado conferido por renders nativos, separado da prova de autorização, em português/inglês; a confirmação móvel aguarda CSS/fontes antes de medir. Títulos longos têm quebra e a aba traz o conteúdo para a área visível no celular.
- 1.226 registros públicos e 1.224 RAWs públicos preservados; snapshots, fontes dos classificadores existentes e regras de recuperação congeladas sem alteração. As 635 classificações novas são revisões separadas.

O detector mecânico do Impeccable não encontrou ocorrências nos arquivos JS/CSS finais. A leitura direta de links Jinja pelo detector é limitada; estilos, fontes e responsividade foram conferidos no navegador. O contexto Impeccable também registra uma preferência de composição visual ainda não definida para futuras páginas de apresentação; ela não altera este workbench em modo Operate.
