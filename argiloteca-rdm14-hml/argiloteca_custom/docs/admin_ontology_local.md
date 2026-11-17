# Administração por ontologia — operação local

**Atualização em 01/11/2026:** os ajustes foram implantados em produção. Consulte o [guia produtivo](admin_production.md). As evidências abaixo mantêm seu escopo histórico local.

Entrega e fechamento documental em 31/10/2026, limitados à instância local de homologação. A administração passa a partir da cadeia Campo → Amostra → Análise → Argilomineral → Publicações e reúne os módulos existentes por tarefa. O primeiro parecer independente é **ship — UX e apresentação local**; a extensão posterior de cores e mapa também foi fechada, com **ship** restrito à correção do único apontamento material, conforme evidências abaixo. Não houve implantação em produção ou alteração dos dados científicos.

Abra a [visão geral local em português](https://127.0.0.1:5101/administration/?ln=pt) com uma sessão administrativa. O mundo visual permanece o da Argiloteca: marrom, laranja CPAA, Catamaran/Lato, Semantic UI, SVG e mascote herdados. A imagem conceitual enviada pelo usuário orientou as cinco entidades; não foi incorporada como imagem de texto. `DESIGN.md` e `.impeccable/design.json` não existiam e continuam ausentes, conforme o escopo de preservação. Este guia e o brief da superfície registram as decisões sem criar ou reparar artefatos globais.

## Arquitetura da informação e implementação

| Área | Trabalho oferecido |
| --- | --- |
| Cadeia científica | Abrir os cinco recortes de registros e suas ferramentas; criar um registro científico. |
| Povoamento | Fontes de dados, visão integrada e atualização dos dados do acervo. |
| Curadoria e relações | Autores/ORCID, conexões, catálogo, mapa, classificação, duplicados e vínculos DRX. |
| Arquivos e preservação | RAW, arquivos restritos, PDFs, remoção/arquivamento e conhecimento do ArgiloClay. |
| Gestão do repositório | Árvore administrativa nativa, ordenada recursivamente, respeitando `visible` e os destinos existentes. |

O pacote `argiloteca/admin_ui/` contém a ativação (`__init__.py`), o catálogo bilíngue e contexto (`navigation.py`), entidades e consulta efetiva (`ontology.py`), a busca manual de lugares (`geocoding.py`) e as rotas GET/POST auxiliares (`views.py`). `argiloteca/ext.py` configura a extensão no boot. Não há nova API de escrita de registros científicos ou migração de banco; o POST de geocodificação consulta um provedor e mantém cache auxiliar SQLite.

Os templates raiz `templates/semantic-ui/invenio_administration/` integram o shell: `base.html`, `index.html`, `index_ontology.html`, `index_legacy.html` e `sidebar/sidenav{,_legacy}.html`. A flag seleciona a visão atual ou o fallback salvo. No pacote, `admin_entity.html`, `admin_sources.html`, `_admin_module_context.html` e `_admin_source_rows.html` integram entidade, fontes e orientação dos módulos. `_scientific_page.html` fornece os SVG de Campo/Amostra, e `argiloclay_robo.html` preserva o mascote. `static/css/admin-ontology.css` e `static/js/admin-ontology.js` cuidam da apresentação e busca local de ferramentas.

A visão geral tem uma ação principal **Novo registro científico**. A busca **Encontrar ferramenta** filtra as entradas já renderizadas no DOM, ignora acentos e não chama uma API nem pesquisa registros científicos. No ambiente verificado, limpar a busca restaura 20 ferramentas; o total depende dos módulos habilitados. Grupos recolhíveis e item ativo orientam a navegação. No celular, o menu começa fechado, fecha por Escape e restaura o foco ao acionador. O assistente fica em fluxo depois do conteúdo, inclusive nas páginas nativas com o novo shell.

## Entidades, campos e grão do censo

Os nomes abaixo correspondem aos blocos reais de `argiloteca/scientific/models.py::BINDINGS`. A regra conta presença de objeto/lista não vazio; não valida completude, identidade física ou conclusão científica.

| Entidade | Campos em `custom_fields` ou regra adicional | Registros na verificação local |
| --- | --- | ---: |
| Campo | `arg:pesquisas_campo` | 1.247 |
| Amostra | `arg:amostras` | 1.247 |
| Análise | `arg:analises`, `arg:pacotes_analiticos` ou `arg:composicao_quimica_global` | 379 |
| Argilomineral | `arg:argilominerais` ou `arg:termo_catalogo` | 1.325 |
| Publicações | `arg:publicacoes_relacionadas` ou `metadata.resource_type.id` iniciado por `publication-` | 6.027 |

O total nativo efetivo foi **6.478 registros**. A consulta lê `rdm_records_metadata` e `rdm_drafts_metadata`: considera publicações ativas (`deletion_status='P'`), exclui versões aposentadas e prefere a edição em rascunho para inspecionar o payload. Um RID publicado com edição conta uma vez e conserva ambos os indicadores de estado. RIDs distintos não são unidos por título ou nome.

As entidades podem se sobrepor: um mesmo registro pode conter campo, amostra, análise e referência bibliográfica. Não some os recortes para obter o total; não interprete suas contagens como pessoas, amostras físicas únicas, quantidade de análises executadas ou evidências minerais confirmadas. As contagens da home são consultas ao acervo no momento da requisição, não um retrato imutável de povoamento, novas coletas ou número de citações. Se a consulta das contagens falhar, a home informa indisponibilidade e mantém os módulos acessíveis.

## Rotas e uso

| Entrada | Rota |
| --- | --- |
| Visão geral | `/administration/` |
| Fontes | `/administration/argiloteca/fontes/` |
| Campo | `/administration/argiloteca/entidades/campo/` |
| Amostra | `/administration/argiloteca/entidades/amostra/` |
| Análise | `/administration/argiloteca/entidades/analise/` |
| Argilomineral | `/administration/argiloteca/entidades/argilomineral/` |
| Publicações | `/administration/argiloteca/entidades/publicacoes/` |
| Importadores existentes | `/administration/openalex/`, `/administration/pangaea/`, `/administration/mendeley/` |
| OAI institucional | `/administration/repositories/?repository=lume` ou `?repository=ufsc` |
| Povoamento/autoria | `/administration/povoamento/`, `/administration/povoamento/authors/` |
| Gestão nativa | `/administration/records`, `/administration/drafts` |
| Mapa e coordenadas existentes | `/administration/mineral-map/` |
| Busca manual de topônimo (POST) | `/administration/argiloteca/geocode` |

Nas entidades, `q` pesquisa título, RID ou a descrição em `custom_fields`, limitado a 150 caracteres. `stage` aceita vazio (todos), `published`, `draft` (somente rascunho) e `editing` (publicação com edição). `published` também inclui publicações em edição. `page` é inteiro positivo; a paginação usa 20 registros e ajusta página acima do total à última página disponível. Entidade desconhecida responde 404; página inválida ou situação desconhecida responde 400. O estado vazio oferece limpar o recorte e abrir a gestão nativa.

Os vínculos dos resultados abrem `/uploads/<RID>` quando há rascunho e `/records/<RID>` nos demais casos. **Descrição científica** e **Novo registro científico** encaminham aos fluxos existentes, com suas permissões e salvamento próprios. A reorganização não altera esses contratos.

O importador de repositórios aceita `repository=lume` ou `repository=ufsc`; uma seleção ausente/inválida mantém LUME. O link UFSC do hub passa o parâmetro e seleciona UFSC no formulário. Isso confirma navegação, não execução ou sucesso de coleta OAI.

## Português, inglês e preferência por cookie

Use `?ln=pt` ou `?ln=en` para abrir uma rota com idioma explícito. A extensão usa o locale resolvido pelo mecanismo existente (`get_locale().language`) para rótulos, links e números. O contexto `au_locale` também preenche o campo oculto `ln` do formulário de entidade e os links de filtro/paginação/limpeza. Assim a preferência definida no seletor de idioma e mantida por cookie continua em uma URL sem `ln` e após a filtragem.

`locale-cookie-verification.log` confirma URL limpa em English, formulário com `ln=en` e resultado filtrado em inglês. Essa correção funcional foi posterior ao parecer visual; não alterou estilos ou as capturas feitas com `ln` explícito. O conteúdo React interno de Registros ainda apresenta alguns rótulos mistos e controles estreitos; a entrega cobre seu shell e navegação, sem aprovação integral desse conteúdo.

## Permissões, leitura e ativação

As rotas da extensão usam a proteção administrativa existente (`admin_only`/`can_review`): sessão autenticada e `administration_permission.can()`. Respostas de consulta têm `Cache-Control: private, no-store` e `X-Robots-Tag: noindex, nofollow`. O censo, a navegação e os filtros são somente leitura. Os módulos apontados continuam com as operações, flags, CSRF e permissões que já possuíam; um link não autoriza importação ou publicação. A visibilidade nativa é preservada, e as ferramentas personalizadas respeitam disponibilidade dos endpoints e flags correspondentes.

`ARGILOTECA_ADMIN_ONTOLOGY_ENABLED` pode ser definido na configuração Flask ou, quando a configuração não contém a chave, pela variável de ambiente. A variável habilita somente com o valor `true` (sem distinguir maiúsculas/minúsculas). Sem valor explícito, a extensão habilita apenas se o hostname de `SITE_UI_URL` for `localhost`, `127.0.0.1` ou `::1`; fora de loopback o padrão é falso. Uma chave já presente na configuração tem precedência sobre o ambiente. Configuração explícita deve usar booleano, por exemplo `ARGILOTECA_ADMIN_ONTOLOGY_ENABLED = False`.

### Rollback documentado; não executado neste fechamento

1. No mecanismo de configuração da instância, defina a flag como o booleano `False`. Se a chave não for definida por configuração Flask, use a variável `ARGILOTECA_ADMIN_ONTOLOGY_ENABLED=false`.
2. Reinicie o serviço da instância para aplicar a decisão no boot.
3. A home e a lateral usam `index_legacy.html` e `sidenav_legacy.html`; CSS/JS e contexto da extensão deixam de ser ativados. As rotas `/administration/argiloteca/fontes/`, `/administration/argiloteca/entidades/.../` e `/administration/argiloteca/geocode` não são registradas no boot desabilitado; o módulo nativo de coordenadas permanece com seus formulários existentes.

O verificador local confirmou o fallback de apresentação com a flag falsa em sua aplicação de teste. Alternar a flag em um processo já iniciado não remove rotas previamente registradas: o reinício é necessário para um rollback completo. Não é preciso remover metadados, reindexar registros ou executar migração de dados para reverter a apresentação. Este guia não executou o rollback ou alterou configuração de produção.

## Marcas e origem dos ativos

As marcas identificam as integrações existentes e não afirmam patrocínio, certificação ou parceria. Foram obtidas em 31/10/2026, servidas localmente em `argiloteca/static/images/sources/` e documentadas em `SOURCES.md` e `sources.json` com URL, data, transformações e SHA-256.

| Arquivo | Origem oficial registrada |
| --- | --- |
| `openalex.png` | [Lockup OpenAlex](https://openalex.org/brand-assets/openalex-lockup.png) |
| `pangaea.png` | [Logo do cabeçalho PANGAEA](https://www.pangaea.de/assets/v.2d6f89e80fb0ee2bf039f8938c1ebe6a/layout-images/pangaea-logo.png) |
| `mendeley.svg` | SVG inline `mdui-logo` do [Mendeley Data](https://data.mendeley.com/) |
| `lume.png` | [Logo LUME UFRGS](https://lume.ufrgs.br/themes/Mirage2Novo/images/logo_lume.png) |
| `ufsc.svg` | [Brasão oficial UFSC](https://identidade.ufsc.br/wp-content/themes/brasilGovInterno/img/brasao_site_ufsc.svg) |
| `orcid.png` | [Logo ORCID](https://info.orcid.org/wp-content/uploads/2021/01/orcid-logo.png) |

Os registros de procedência descrevem os quatro PNGs com metadados de origem embutidos e pixels inalterados; guardam também o hash original antes da inclusão dos metadados. Mendeley é a extração integral da marca SVG oficial, acrescentando apenas `xmlns` para uso independente. O brasão UFSC foi preservado. Não houve geração por IA, recoloração ou nova ilustração; o mascote existente foi reutilizado. Na conferência documental, os hashes atuais de seis marcas conferiram com `sources.json`; o scan existente registra quatro rasters e zero origens ausentes.

## Validação histórica da primeira fase

As evidências históricas estão em `output/admin-ontology-20261031/`, na raiz do projeto. O fechamento leu os arquivos e conferiu hashes/presença; não reexecutou testes, navegador ou detector.

| Evidência | Resultado registrado |
| --- | --- |
| `verified-interface.json`, `runtime-verification.log` e verificador local | 15 rotas em PT e EN com 200; anônimo 403, entradas inválidas 400/404, UFSC selecionada, filtros/estado vazio e fallback legado. |
| `unit-tests.log` | 10 testes de entidades, regras, binds e ativação. |
| `openalex-regression.log` | 156 aprovados. Os seis erros iniciais eram localização de fixtures no ambiente, corrigida antes da execução final. |
| `providers-and-population-regression.log` | 23 povoamento + 35 repositórios + 27 Mendeley + 16 PANGAEA aprovados. |
| `browser-captures.log` | Dez rotas/estados PT em desktop 1440 px e celular 390 px: 200 e largura do documento igual ao viewport. |
| `browser-interactions.log` | ORCID: uma ferramenta; vazio; limpar restaura 20; Amostra abre; uma ação de criação; UFSC selecionada; Escape fecha menu e restaura foco. |
| `locale-cookie-verification.log` | Idioma English preservado na URL limpa, no formulário e no resultado filtrado, sem escrita nativa. |
| `source-manifest.json` | Snapshot histórico de 31 arquivos, conferido naquela fase, incluindo a correção de locale; não representa o estado posterior à extensão de mapa. |
| `asset-provenance-scan.log`, `detector.json` | Quatro rasters/zero origens ausentes; detector `[]`, limitado para CSS/Jinja e sem matriz completa de contraste. |

Na primeira fase foram **267 testes distintos aprovados**; não foram todos reexecutados para a extensão de mapa. As 13 capturas finais em `.impeccable/review/admin-ontology/` incluem home PT/EN, fontes, Análise, Mendeley, Registros, menu móvel e estado vazio. O parecer `.impeccable/review/admin-ontology/finish-review.md` registra inspeção individual de todas elas. Neste fechamento foram confirmados 13 arquivos PNG válidos e larguras de 1440/390 px; não foi aberta nova rodada visual. O primeiro passe mostrou sobreposição do rodapé, corrigida antes das capturas finais; o parecer final registra ausência dessa oclusão.

O parecer visual não cobre uma matriz completa de contraste, leitores de tela, outros viewports, carregamento/falhas remotas, autenticação em produção ou validade científica dos registros. O token de leitura ORCID permanece ausente. A ausência de `buildPath` apontada pelo contexto foi apenas registrada; não motivou reparo global. Na primeira fase não houve coleta externa, importação/publicação, escrita nativa, alteração de arquivos científicos ou deploy em produção. A extensão abaixo fez consulta externa manual Photon e carregou tiles, sem escrita nativa.


## Cores da administração

As cores identificam a cadeia científica e mantêm os rótulos e SVG existentes; o marrom Argiloteca, laranja CPAA, Catamaran/Lato e componentes nativos permanecem. Os pares de texto/fundo reais de `static/css/admin-ontology.css` são:

| Entidade | Texto/ícone | Fundo |
| --- | --- | --- |
| Campo | `#285e46` | `#e5f2ea` |
| Amostra | `#765817` | `#fbefd0` |
| Análise | `#245e78` | `#e4f1f8` |
| Argilomineral | `#814321` | `#f7e6d9` |
| Publicações | `#624577` | `#f0e8f7` |

Povoamento usa azul, curadoria verde e preservação violeta. Cor não é o único sinal: nomes, ícones, sublinhado/estado ativo e foco continuam presentes. Marcas das fontes não foram recoloridas. No mapa, círculos azuis identificam pontos de registros e losango laranja identifica proposta não publicada, com legenda textual.

## Mapa e coleta de coordenadas

Abra o [módulo local de coordenadas](https://127.0.0.1:5101/administration/mineral-map/?ln=pt) em uma sessão administrativa. O módulo preserva os formulários nativos; a extensão está em `admin_mineral_map.html`, `_admin_coordinate_map.html`, `static/css/coordinate-map.css`, `static/js/coordinate-map.js`, `admin_ui/geocoding.py` e `scientific/catalog_views.py`. Leaflet 1.9.4 é servido localmente em `static/vendor/leaflet-1.9.4/`; não há novo esquema de metadados científicos.

1. Abra um registro pelo identificador ou pelo ponto de um registro. **Carregar mapa** inicia o mapa; os tiles OpenStreetMap são requisitados pelo navegador, com atribuição visível. **Enquadrar registros** ajusta a visão aos pontos carregados.
2. O mapa reúne coordenadas válidas dos 25 registros públicos da página e do registro autorizado aberto, com este priorizado, até 2.000 pontos. Ele não representa todos os registros do repositório. Popup oferece título, identificação do local, coordenadas e link de revisão.
3. Para localizar por nome, preencha **Topônimo ou nome do lugar**, incluindo município/estado/país, e acione **Buscar coordenadas**. A busca é manual, sem autocomplete, com 3–180 caracteres e até cinco candidatos. Selecione um candidato para vê-lo no mapa. Alternativamente, clique no mapa e arraste o losango para ajustar uma proposta.
4. Escolha o destino existente de amostra, argilomineral ou localização legada oferecido pelo registro. Trocar o destino descarta a proposta anterior. **Preencher coordenadas para revisão** preenche somente latitude/longitude daquele formulário, destaca-o e leva foco à latitude. Outros alvos conservam seus valores.
5. Confira coordenadas, fonte, ponto de coleta e datum. Somente a ação de publicação do formulário nativo salva o registro, com permissões, CSRF, revisão e checagem de edição/rascunho ativo existentes. Carregar, buscar, selecionar e preencher não publicam nem salvam automaticamente.

Mapa e geocodificador trabalham em WGS 84 (EPSG:4326), mas não convertem o datum do registro. Um topônimo pode ser o centro de um município, não o ponto da coleta; os resultados são propostas. A ordem GeoJSON longitude/latitude é interpretada corretamente e valores finitos/faixas são validados. O preenchimento arredonda a seis casas; isso não afirma precisão de campo nem autoriza inferir coordenadas ausentes a partir de um nome sem conferência.

Mapa e ferramentas empilham abaixo de 1050 px; a altura do mapa passa de 500 para 420 px e para 330 px abaixo de 600 px. O foco visível, os campos manuais e a busca por texto permanecem disponíveis. O salto **Ir para o conteúdo principal** fica recortado a 1×1 px quando sem foco e reaparece no topo do viewport ao receber foco pelo teclado. A aplicação de proposta conserva foco na latitude. Leaflet usa `animate:false` e animações de zoom desativadas porque o CSS herdado impedia concluir o zoom; a chegada efetiva ao local foi verificada.

### Configuração e dependências externas

A flag `ARGILOTECA_ADMIN_ONTOLOGY_ENABLED` ativa a extensão do módulo e registra a rota de geocodificação no boot, com o mesmo padrão local/loopback descrito acima. O POST de mesma origem `/administration/argiloteca/geocode` exige sessão administrativa e CSRF; o limite do corpo é 4 KiB. Ele envia ao provedor somente o texto explicitamente submetido, sem payload científico de registro. O endpoint padrão é `https://photon.komoot.io/api/` e não exige chave de API.

Para usar uma instância Photon confiável, configure `ARGILOTECA_GEOCODER_URL` em `invenio.cfg` com uma URL HTTPS sem credenciais, query ou fragmento e reinicie a instância. A configuração não deve vir da entrada do usuário. O código recusa redirects; usa timeout de conexão/leitura de 4/10 segundos e resposta máxima de 1 MiB. Consulte a documentação primária do [Photon](https://github.com/komoot/photon); a disponibilidade do servidor demo não é garantida e o formulário permite digitação manual.

O cache auxiliar é compartilhado entre workers em `<ARGILOTECA_OPENALEX_QUEUE>/geocoding/places.sqlite3`; sem `ARGILOTECA_OPENALEX_QUEUE`, usa `<instance_path>/data/geocoding/places.sqlite3`. A pasta é criada com modo 0700 e o arquivo com 0600. A chave é hash do endpoint/texto normalizado, os candidatos ficam armazenados por sete dias e no máximo 512 entradas. Buscas repetidas válidas retornam cache sem rede. A reserva SQLite limita chamadas externas a uma a cada 1,1 segundo entre workers; resposta 429 orienta aguardar dois segundos. Há regra estreita no `.gitignore` para o cache gerado; ele não é metadado científico ou fonte normativa de coordenadas.

Tiles vêm de `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, por carregamento normal do navegador após a ação de mapa/resultado, sem prefetch ou download em massa. Preserve a atribuição visível e a [política de tiles OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/). Falha no fundo mantém pontos/formulários; busca vazia pede desambiguação, e indisponibilidade permite repetir ou preencher manualmente. Não há promessa de uso offline ou serviço externo contínuo.

### Evidências atuais e fechamento de cores/mapa

As evidências atuais estão em `output/coordinate-map-20261031/`; as da seção anterior são históricas. Este fechamento documental leu fontes, relatórios e logs, conferiu **42/42 SHA-256 de fontes e 13/13 de capturas** no manifesto atual, sem divergências, e não reexecutou testes, navegador, detector ou contexto. Somente este guia e o brief da superfície foram atualizados.

| Evidência | Resultado registrado |
| --- | --- |
| `geocoding-unit-tests.log` | 12 testes aprovados de parsing, limites, cache, throttle e falhas. |
| `coordinate-catalog-tests.log` | 5 testes existentes de coordenadas/catálogo/XML aprovados. |
| `ontology-tests.log` | 10 testes de regressão aprovados; total atual 27, sem alegar reexecução dos 267 históricos. |
| `integration.json` e `integration.log` | Porto Alegre retornou cinco candidatos reais e repetição por cache; PT/EN 200, anônimo 403, CSRF 400, inválido 422, limite 429, indisponibilidade 503. SHA do registro selecionado permaneceu igual; sem POST de escrita nativa. |
| `browser-check.json` e log | 13 capturas em desktop 1440/celular 390, sem overflow/pageerrors; tiles reais, 50 pontos, cinco resultados reais em cache, proposta por clique, zoom real 12, isolamento do segundo alvo e ausência de autosave. Falha/vazio foram simulados, sem serem apresentados como sucesso externo. |
| Capturas de teclado e `browser-check.json` | Primeiro Tab revela o salto; Enter foca main em ambos os tamanhos; foco de latitude volta a recortá-lo. |
| `admin-regression.log` | 30/30 GETs PT/EN com 200; fallback, UFSC, filtros, cookie de idioma e censo preservados. |
| `contrast.json` | Nove pares nomeados, de 5,74:1 a 9,73:1; medição local, sem certificação completa de contraste/acessibilidade. |
| `detector.json` | `[]` antes do ajuste CSS final de salto ao conteúdo; não houve segundo passe. |
| `source-manifest.json` | 42 fontes atuais e 13 capturas finais com hashes conferidos; substitui o snapshot histórico de 31 fontes como referência do estado implementado. |

O parecer `.impeccable/review/admin-coordinate-map/finish-review.md` abriu as 11 capturas originais e registrou cinco seções, com **fix** somente para o salto ao conteúdo que encobria proposta/aviso. Após a correção focada, `finish-verdict.md` reabriu os quatro estados corrigidos e duas capturas de teclado: único apontamento resolvido, sem regressão visível, **ship**. Esse parecer final avalia a correção pontuada, não uma segunda auditoria de toda a superfície ou certificação do backend. As 13 capturas finais atuais ficam nessa pasta; as capturas da ontologia da fase anterior permanecem históricas.

A extensão está fechada localmente. Houve consulta manual externa e carregamento de tiles; não houve publicação/importação, escrita nativa de coordenadas, alteração de arquivos científicos ou deploy. A validade científica das coordenadas, disponibilidade futura de Photon/tiles, leitores de tela, outros viewports e matriz completa de contraste permanecem fora do atestado. Marcas e proveniência anteriores foram preservadas, sem novo bitmap de entrega ou geração de imagem. A ausência prévia de `DESIGN.md`/`.impeccable/design.json`, o `buildPath` ausente e os limites do React foram registrados sem reparo global ou promoção a regras de design.
