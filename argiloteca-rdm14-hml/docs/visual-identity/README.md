# Identidade visual Argiloteca — parceria UFRGS–Petrobras

Implementação na homologação local de InvenioRDM **14.0.4**, em 18/10/2026.
Prévia: <https://127.0.0.1:5101/>. Página institucional: <https://127.0.0.1:5101/sobre>.
Publicação externa e domínio público foram adiados expressamente pelo responsável.

## Diagnóstico e direção

A implementação existente, documentada em `../../INTERFACE.md`, já estabelece
marrom como cor principal, fundos claros, Lato local e ícones SVG compartilhados.
O arquivo `static/images/LOGO-CPAA.png` é a identificação atualmente configurada
como marca da Argiloteca; foi preservado, sem retoques. Não foi criado um logo novo.
A abertura anterior repetia buscas, tinha uma apresentação extensa e deixava a
parceria restrita ao rodapé. O rodapé não continha as marcas das instituições.

A direção é um refinamento do sistema existente: ações e navegação continuam em
marrom; as cores institucionais ficam na assinatura da parceria. A consulta recebe
uma busca única na abertura, com acesso aos módulos, imagens e comunidades reais.
A introdução usa um título curto e descrição funcional; a apresentação institucional
mais extensa fica em `/sobre`. Nenhum dado, número de acervo, contrato, papel de
financiamento ou resultado científico foi inventado.

A assinatura aprovada pelo responsável é:
**Argiloteca é um dos resultados do Projeto de P&D: BASE DE DADOS ESTRUTURADA DE DEPÓSITOS DE ARGILAS DO BRASIL E ANÁLOGOS NO MUNDO, uma parceria entre UFRGS e Petrobras.**

## Referências efetivamente examinadas

As quatro páginas institucionais foram renderizadas em Chromium nas larguras
1440 e 390 px. As capturas ficam em `../../../output/playwright/reference-*.png`.
O leitor web não conseguiu obter a UFRGS; a inspeção foi possível no navegador.
No portal UFRGS havia uma camada de consentimento visível nas capturas iniciais;
não se extrapola a observação para conteúdo encoberto. Os manuais foram lidos
como documentos, separadamente da observação dos portais.

| Elemento observado ou documentado | Fonte oficial | Finalidade | Adaptação realizada |
| --- | --- | --- | --- |
| Marca universitária, nome completo e navegação institucional separados do conteúdo | [Portal UFRGS](https://www.ufrgs.br/site/) | Identificar a instituição e organizar as tarefas | Marca Argiloteca principal; parceria em texto no cabeçalho; navegação científica mantida |
| Pacotes de versões cromáticas, marca promocional e brasão com usos distintos | [Marca UFRGS](https://www.ufrgs.br/site/marca-ufrgs/) | Selecionar arquivo apropriado, sem reconstrução | Marca promocional oficial azul/vermelho sobre branco; não se usa brasão improvisado |
| Título conciso, ação destacada e detalhes amarelos; navegação móvel própria | [Sustentabilidade Petrobras](https://petrobras.com.br/sustentabilidade) | Dar hierarquia à comunicação institucional | Abertura curta, busca prioritária e pequenos divisores institucionais; fotos/copy ambientais não foram transplantadas |
| Assinatura horizontal preferencial, versões originais e proteção da marca | [Marca Petrobras](https://petrobras.com.br/quem-somos/nossa-marca) e pacote de aplicação vinculado | Preservar a identificação institucional | Vetor horizontal original; 189 px de largura; fundo branco e espaço livre |
| Vocabulário de refinamento, verificação visual e limite de duas rodadas | [Impeccable](https://impeccable.style/) / [repositório oficial](https://github.com/pbakaus/impeccable) | Conduzir implementação e revisão | Skill local 4.6.0, referências `polish` e `craft-floor`; detector manual e revisão renderizada |

O mecanismo de override Jinja e os componentes compartilhados da instância foram
mantidos. Não se editou código de dependências instaladas. A documentação online
InvenioRDM consultada retornou 403; a versão e os templates compatíveis foram
confirmados no runtime local e na documentação da instância.

## Implementação e manutenção

- `templates/semantic-ui/invenio_app_rdm/header_frontpage.html`: nome, propósito,
  assinatura e única busca inicial, com os endpoints existentes.
- `intro_section.html`: apresentação concisa, exploração do acervo e catálogo;
  galeria de nove comunidades com imagens científicas existentes.
- `header.html`: identificação principal preservada; nomes das parceiras e link Sobre.
- `footer.html`: assinatura institucional compartilhada, marcas e links anteriores.
- `site_footer.html`: tecnologia, idioma e link HTTPS.
- `argiloteca_custom/argiloteca/templates/semantic-ui/argiloteca/_partnership.html`:
  macro reutilizável de marcas e links oficiais com nomes acessíveis.
- `institutional.html` e rota `/sobre`: descrição institucional fornecida e condições
  de acesso correspondentes ao comportamento real do repositório.
- `argiloteca-theme.css`: tokens e componentes institucionais globais; correção do
  alinhamento da grade nativa em tablet.
- `argiloteca-home-record.css`: estilo da abertura extraído do HTML; ajustes de
  hierarquia e galeria, preservando estilos de registros e dados científicos.
- `translations/{en,pt}/LC_MESSAGES/messages.po`: novos textos nos dois idiomas,
  com MO e dicionários JavaScript gerados pelo compilador existente. O catálogo
  React local `translations/frontend/invenio_app_rdm.pt.json` corrige a mensagem
  de busca sem resultados; essa alteração exige recompilar os assets da imagem.

Os templates, estilos, pacote e traduções são montados pela composição local.
`scripts/compile-translations` compila e valida os catálogos; reiniciar `web-ui`
e `web-api` recarrega Python e gettext. A imagem pode ser reconstruída pelo fluxo
normal em outra instalação. Não houve migração, exclusão ou reindexação de dados.

## Tokens e proveniência

Cores derivadas da interface são adaptações existentes; não são apresentadas
como cores oficiais das instituições. Os quatro tokens institucionais vieram dos
valores reais dos SVGs oficiais; os dois da UFRGS são usados no arquivo original,
sem aplicação adicional à navegação, aos mapas ou às séries científicas.

| Token | Valor | Origem | Função | Exemplo |
| --- | --- | --- | --- | --- |
| `--arg-color-primary` | `#79583c` | Tema existente Argiloteca | Identidade de interface | Referência cromática principal |
| `--arg-color-primary-strong` | `#6f4f34` | Adaptação existente | Ações e títulos | Buscar, Explorar acervo |
| `--arg-color-primary-hover` | `#543a26` | Adaptação existente | Interação | Hover dos botões |
| `--arg-color-text` | `#2f2a24` | Tema existente | Leitura | Parágrafos institucionais |
| `--arg-color-muted` | `#665d53` | Tema existente | Texto secundário | Propósito e assinatura |
| `--arg-color-surface` | `#ffffff` | Tema existente | Superfície | Fundo das marcas |
| `--arg-color-surface-page` | `#f5f2ec` | Tema existente | Fundo de leitura | Página Sobre |
| `--arg-color-surface-soft` | `#f5f0e8` | Tema existente | Apoio | Legendas e subrodapé |
| `--arg-color-surface-analytic` | `#fbf7f0` | Tema existente | Área científica | Galeria inicial |
| `--arg-color-border` | `#d7cabe` | Tema existente | Separação | Rodapé e seções |
| `--arg-color-control-border` | `#968575` | Tema existente | Limite de controles | Campo de busca |
| `--arg-color-focus` | `#27666b` | Tema existente | Teclado | Contorno de foco |
| `--arg-color-valid` | `#256347` | Tema existente | Sucesso | Estados existentes preservados |
| `--arg-color-warning` | `#80530d` | Tema existente | Aviso | Estados existentes preservados |
| `--arg-color-error` | `#a03432` | Tema existente | Erro | Estados existentes preservados |
| `--arg-partner-petrobras-green` | `#008542` | SVG oficial Petrobras | Assinatura | Divisor superior da composição |
| `--arg-partner-petrobras-yellow` | `#fdc82f` | SVG oficial Petrobras | Assinatura | Divisor inferior da composição |
| `--arg-partner-ufrgs-blue` | `#0069a7` | SVG oficial UFRGS, versão 01 | Identidade institucional | Próprio SVG original |
| `--arg-partner-ufrgs-red` | `#e30613` | SVG oficial UFRGS, versão 01 | Identidade institucional | Próprio SVG original |
| `--arg-font-ui` | `Lato, Helvetica Neue, Arial, sans-serif` | Família local existente | Tipografia | Texto, navegação e controles |
| `--arg-space-institutional` | `2rem` | Adaptação desta interface | Espaço institucional | Rodapé e página Sobre |

## Arquivos de marca

`argiloteca_custom/argiloteca/static/images/partners/sources.json` registra URLs,
data, hashes SHA-256 e ausência de alterações dos dois vetores incorporados.

- **Argiloteca/CPAA:** `static/images/LOGO-CPAA.png`, arquivo já configurado no
  projeto. Conservado integralmente; origem externa histórica não documentada.
- **UFRGS:** arquivo `Logo UFRGS formato SVG-01.svg`, do [pacote SVG oficial](https://www.ufrgs.br/site/wp-content/uploads/2025/05/Logo-UFRGS-SVG.zip),
  copiado como `ufrgs.svg`. Azul/vermelho, viewBox 600 × 500; dimensão de interface
  100 × 83,33 px, proporcional. O [manual disponibilizado pela UFRGS](https://www.ufrgs.br/site/wp-content/uploads/2025/04/manual.pdf)
  distingue marca promocional e marca oficial, orienta posicionamento e convivência.
- **Petrobras:** [vetor do portal oficial](https://petrobras.com.br/documents/2677942/2678045/logo.svg/64b59d8a-d175-c374-189d-af798dea2241?version=1.0&t=1686665076000),
  copiado como `petrobras.svg`; viewBox 189 × 37. Regras conferidas no manual
  revisão 9, vinculado na página de marca: horizontal preferencial, mínimo digital
  de 100 px, área livre pela altura das letras BR e distância entre marcas pela
  altura da assinatura. Aplicação com 189 px de largura, padding de 32 px, vão
  horizontal de 48 px e vertical de 37 px; UFRGS à esquerda/acima e mais alta.

Em celulares, as marcas podem ocupar duas linhas, mantendo dimensões e áreas
livres; não há filtros de recoloração, cortes ou fontes recriadas. A composição
é uma aplicação de interface; não representa homologação formal pelas áreas de
marca das instituições. Nenhuma fonte ou imagem remota foi acrescentada ao
carregamento do site. Novos vetores: 14.062 bytes no total, antes da compressão HTTP.

## Evidências e limites

As capturas antes/depois equivalentes de home, busca e registro estão em
`../../../output/playwright/brand-{before,after}-*.png`, em 1440 e 390 px.
As comparações em inglês usam o mesmo idioma, registro e consulta. A nova página
institucional não existia antes e tem capturas apenas depois. `brand-final-*`
contém detalhes da confirmação final. Os arquivos não são capturas de produção.

A revisão usa Chromium automatizado, com aceitação do certificado apenas na
configuração local do navegador. As chamadas HTTP de regressão usam a CA local,
sem desativar a verificação TLS. Não se testa coleta externa nesta tarefa.
Os resultados de execução são registrados em `verification.json`.

Objetivo: WCAG 2.2 AA. Não se declara conformidade integral: leitura por tecnologia
assistiva, navegadores Safari/Firefox, telefone físico e zoom real do navegador
não foram testados. Os estados de validação científica, carregamento, permissão
ou erro já existentes foram preservados; a página institucional é renderizada
no servidor e não introduz novos estados assíncronos.

### Resultado final

- 32 combinações: home, busca, registro e Sobre × inglês/português × 1440,
  768, 390 e 320 px. Todas responderam 200, sem rolagem horizontal ou imagens
  quebradas, sem erros de console ou exceções JavaScript.
- Busca textual, seleção mineral, faceta Dataset, menu móvel/Escape, foco de
  teclado, nomes acessíveis das marcas e preferência por movimento reduzido
  conferidos. A busca inicial fica entre 221 e 281 px no celular de 390 px.
- A mensagem vazia foi corrigida no catálogo React e observada na imagem ativa:
  “Não encontramos resultados para …”, com as ações Recomeçar e Dica.
- Depósito científico anônimo redireciona ao login. API de registro, Identify
  e ListMetadataFormats locais passaram novamente após a ativação.
- Contraste mínimo medido nos textos alterados selecionados: 6,45:1. Este
  resultado não é uma auditoria de todo o acervo, gráficos ou site.
- Catálogos: 3.718 entradas por idioma; cobertura de 1.529 mensagens marcadas,
  sem mensagens ausentes, vazias/fuzzy ou problemas de placeholders.
- Impeccable: detector manual sem achados; inspeção visual em desktop e celular.
- Imagem ativa: `argiloteca-rdm14-hml:partnership-20261018`, também sob a tag
  canônica `14.0.4`. Web UI, API, worker e scheduler saudáveis na mesma imagem.

A compilação encontrou uma falha do Docker Engine. O responsável autorizou
explicitamente reiniciar o Docker; os serviços anteriormente ativos foram
restaurados, e a compilação terminou com o lockfile congelado. A imagem anterior
foi preservada como `argiloteca-rdm14-hml:before-partnership-20261018`.

Infraestrutura preexistente observada: ao reiniciar, o frontend Nginx regenerou
a configuração com o certificado de teste do template. Os caminhos do certificado
e chave locais anteriormente ativos foram restaurados no contêiner e o HTTPS
foi verificado com a CA anterior. A configuração de TLS externa/persistente não
foi redesenhada nesta tarefa; o mecanismo de geração do template continua sendo
uma pendência de infraestrutura para futuros reinícios/recriações do frontend.
Não foram publicados domínio, namespace, XSD ou endpoint externo.

### Comparação da página inicial

Capturas equivalentes em inglês, com a mesma largura. As imagens finais da home
foram refeitas em uma sessão limpa para evitar artefatos de composição de capturas
longas após a matriz de testes. A página institucional final também foi conferida
nessa sessão: um cabeçalho, um título principal e um rodapé.

| Tamanho | Antes | Depois |
| --- | --- | --- |
| Desktop, 1440 px | [Antes](../../../output/playwright/brand-before-home-desktop.png) | [Depois](../../../output/playwright/brand-after-home-desktop-en.png) |
| Celular, 390 px | [Antes](../../../output/playwright/brand-before-home-mobile.png) | [Depois](../../../output/playwright/brand-after-home-mobile-en.png) |

[Institucional no celular](../../../output/playwright/brand-final-about-mobile.png)
· [Assinatura e rodapé no celular](../../../output/playwright/brand-partnership-footer-mobile.png)


### Refinamento CPAA aprovado em 19/10/2026

Catamaran local (SIL OFL 1.1) nos títulos, cabeçalhos e marca, inclusive títulos dos registros recentes; a apresentação dos registros é preservada. Arquivos WOFF2 e licença estão em `argiloteca_custom/argiloteca/static/fonts/catamaran/`. Laranja #e37f1d nos separadores, marrom #6f4f34 nos botões primários. O laranja não é usado como texto de baixo contraste.

Rodapé inclui CPAA/UFRGS/Petrobras, botão da equipe e contato com ícones SVG: Campus do Vale, Agronomia 9500; 51 3308 – xx xx; argilas@ufrgs.br. Número mantido como fornecido, sem link de chamada. Links textuais Sobre o CPAA e Repositório de dados baseado em InvenioRDM foram retirados conforme pedido.

Verificação PT/EN e celular/desktop: 30 cenários passaram, incluindo página de registro e login. Evidências em `output/playwright/cpaa-typography-contact/` na raiz do checkout.
