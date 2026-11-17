# Padrão de interface da Argiloteca 14

## Telas pequenas

`argiloteca-mobile.css` concentra as adaptações móveis, carregadas uma vez pelo
template global. O menu mantém os eventos nativos de abertura, fechamento e
Escape; até 991 px, o painel usa a altura dinâmica da janela, rolagem própria e
botão de fechar fixo durante a rolagem. Os rótulos Menu e Fechar permanecem visíveis.

Até 767 px, botões, paginação, filtros e links de navegação têm área de toque de
pelo menos 44 px. Campos usam 16 px e selects nativos têm aparência customizada
para preservar a altura no Safari. Os cinco módulos continuam visíveis em duas
colunas; filtros e ações longas podem ocupar uma linha inteira. Tabelas e gráficos
científicos mantêm seus próprios comportamentos, sem ocultar colunas ou séries.

Ao mudar controles, conferir 320 e 375 px, orientação horizontal e desktop. A
revisão de 16/10/2026 usa a aplicação real no modo responsivo do Safari, não um
telefone físico; evidências em `operations/interface-v14-20261016/mobile-adaptation/`
na raiz do workspace.

Implementado em 16/10/2026 com a skill Impeccable. A identidade utiliza os tons
terrosos da Argiloteca, superfícies claras e foco em verde azulado. Lato é a
fonte já disponível no projeto; nenhum serviço de fontes foi acrescentado.

## Fontes de implementação

- `argiloteca_custom/argiloteca/static/css/argiloteca-theme.css`: tokens globais, cabeçalho, controles e estados.
- `argiloteca_custom/argiloteca/static/css/argiloteca-scientific.css`: navegação e componentes científicos compartilhados.
- `argiloteca_custom/argiloteca/templates/semantic-ui/argiloteca/_scientific_page.html`: macros de ícones, navegação, títulos e estados.
- `templates/semantic-ui/invenio_app_rdm/page.html`: carrega os dois estilos globais uma vez.
- `templates/semantic-ui/invenio_app_rdm/header.html`: marca, menu nativo, conta e barra de módulos.

Os overrides de `page.html` e `header.html` derivam dos templates nativos do
Invenio App RDM 14.0.4. Ao atualizar o framework, compare os blocos e controles
com a nova versão. Os originais desta implementação estão no diretório de
operações, em `native/`.

## Cores

| Uso | Token | Valor |
| --- | --- | --- |
| Ações principais e módulo ativo | `--arg-color-primary-strong` | `#6f4f34` |
| Hover principal | `--arg-color-primary-hover` | `#543a26` |
| Texto | `--arg-color-text` | `#2f2a24` |
| Texto secundário | `--arg-color-muted` | `#665d53` |
| Fundo da página | `--arg-color-surface-page` | `#f5f2ec` |
| Superfícies | `--arg-color-surface` | `#ffffff` |
| Fundo de apoio | `--arg-color-surface-analytic` | `#fbf7f0` |
| Contorno de controles | `--arg-color-control-border` | `#968575` |
| Foco de teclado | `--arg-color-focus` | `#27666b` |
| Sucesso | `--arg-color-valid` | `#256347` |
| Atenção | `--arg-color-warning` | `#80530d` |
| Erro/ação destrutiva | `--arg-color-error` | `#a03432` |

Reutilize os tokens; evite novas paletas locais. Verde, âmbar e vermelho são
reservados a estados com significado. As cores das curvas DRX, legendas e
marcadores de mapas continuam vinculadas aos dados científicos.

## Ícones e controles

Use `render_icon(nome)` junto ao texto visível da ação. O SVG usa 20 px,
`currentColor` e traço de 1,75; ícones decorativos têm `aria-hidden="true"`.
Ações representadas apenas por ícone precisam de nome acessível no botão/link.
Os nomes incluem `map`, `catalog`, `minerals`, `drx`, `analyses`, `search`,
`communities`, `dashboard`, `requests`, `refresh`, `layers`, `image`, `expand`
e `upload`. Controles internos nativos do Invenio mantêm seus componentes.

```jinja
{% from "semantic-ui/argiloteca/_scientific_page.html" import render_icon with context %}
<a class="ui button" href="{{ url_for('argiloteca.mapa_argilominerais') }}">
  {{ render_icon('map') }} {{ _('Ver no mapa') }}
</a>
```

Botões customizados usam alvo mínimo de 44 px, espaço entre ícone e texto e
raio de 6 px. Não remova o contorno de `:focus-visible`. Preserve os atributos
`hidden` nos controles condicionais para que estilos de layout não os revelem.

## Navegação

A barra global aparece uma única vez, antes das trilhas de navegação:
Mapa → Catálogo de nomes → Vocabulário → Comparação DRX → Análises.
O módulo atual usa `aria-current="page"`, peso de fonte e fundo destacado.
Em telas estreitas, a barra usa duas colunas; o último item ocupa a linha.
Acervo, Comunidades e Meu painel ficam no menu principal. O menu de conta e
o botão de menu móvel continuam sendo os controles nativos do Invenio.

Páginas novas devem herdar a base e usar `render_scientific_header` para título
e trilha. Não chamem `render_module_nav` novamente e não importem os estilos
globais por página. Use `url_for` para preservar o ambiente e a porta local.

## Validação e aplicação

Evidências: `../../../operations/interface-v14-20261016/`. Os testes cobrem
renderização, presença única da navegação/estilos, arquivos estáticos, links,
CSP e dados do mapa. Contrastes de nove pares de tokens foram calculados;
isso não substitui uma auditoria completa de acessibilidade das páginas.

Após editar templates já carregados, reinicie somente `web-ui` para limpar o
cache. Ao alterar CSS, atualize o parâmetro de versão na base para invalidar o
cache do navegador. Os arquivos são persistentes no projeto e entram nas
próximas imagens Docker.

## Estados de interação revisados em 16/10/2026

Defina sempre a cor do texto/ícone junto com o fundo em hover, foco, pressionado
e selecionado. O menu claro não usa `inverted`. Botões secundários usam
`--arg-color-secondary` e `--arg-color-secondary-hover`; ações negativas
contornadas usam `--arg-color-error`. Os controles do Atlas e da Rede
geoquímica usam fundos opacos para manter o contraste em painéis claros.

A matriz em `../../../operations/interface-v14-20261016/interaction-audit/`
compara 66 espécimes de componentes com os estilos reais, em cinco estados
e duas larguras. `build_fixture.py` monta os espécimes isolados; sirva somente
essa pasta em um servidor local temporário e abra `index.html`. Os estados
nessa matriz são simulados por classes com especificidade equivalente às
pseudoclasses. `live-controls.html` usa CSS sem transformação para conferir
cliques e foco de teclado nos controles corrigidos. Essas verificações não
substituem testes dos fluxos da aplicação ou de componentes futuros.

## Parceria UFRGS–Petrobras — 18/10/2026

A identidade principal e os estados científicos são preservados. O cabeçalho
identifica as parceiras, a abertura concentra uma única busca e `/sobre` apresenta
o texto institucional. O rodapé utiliza a macro `_partnership.html`, com vetores
oficiais sem alterações e área própria de proteção. Fontes, tokens, proveniência
e verificações estão em [docs/visual-identity/README.md](docs/visual-identity/README.md).
Não usar as cores institucionais para substituir legendas ou significados das
curvas, mapas ou classificações científicas.

## Restauração com registros recentes preservados — 18/10/2026

A pedido do responsável, a reformulação LIRA foi desfeita. Cabeçalho, abertura,
coleções e estilos globais voltaram aos arquivos anteriores. Foi preservada
apenas a apresentação dos registros recentes: três colunas no computador, uma
coluna no celular, consulta nativa por data e três registros. Os estilos ficam
em `argiloteca-recent-records.css`, carregado somente na inicial e restrito à
seção. A lista mantém o componente nativo e seus estados de acesso.

## Administração e formulários — 18/10/2026

Os overrides em `templates/semantic-ui/invenio_administration/` usam os tokens
existentes e os ícones de `_scientific_page.html`. O depósito geral e o científico
compartilham `deposit_navigation.html`; o editor científico adota a hierarquia
de conteúdo e ações do formulário nativo. Relações por IDs ficam junto aos campos.
Detalhes, evidências e limites: [docs/admin-deposit-ux/README.md](docs/admin-deposit-ux/README.md).
