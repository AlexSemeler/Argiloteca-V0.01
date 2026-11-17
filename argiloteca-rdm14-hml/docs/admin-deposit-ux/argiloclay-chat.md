# ArgiloClay-Robo — interface independente

Registro da interface entregue em 19/10/2026. A rota `/argiloclay` apresenta uma conversa de pesquisa com fontes recolhíveis, em português e inglês, antes da conexão de modelo, dados, RAG ou MCP. A revisão Impeccable recebeu `disposition: ship` para esta fase demonstrativa.

## Overview

O usuário escolheu conversa central e fontes em painel lateral recolhível. Trata-se de uma superfície Operate construída diretamente em código, sem composição visual aprovada para reprodução. A janela usa a marca Argiloteca e o mascote existente; não contém menus nem rodapé institucionais do Invenio.

Esta documentação descreve a extensão local. `PRODUCT.md`, `.impeccable/briefs/argiloclay-chat.md` e o código existente orientam sua manutenção. Não estabelece nova identidade, metáfora de marca ou regras globais. A ausência preexistente de `DESIGN.md` e `.impeccable/design.json` foi preservada deliberadamente.

Scopus AI e LeapSpace são referências de fluxo de pesquisa e inspeção de fontes indicadas pelo usuário. As páginas oficiais são [Scopus AI](https://www.elsevier.com/en-au/products/scopus/scopus-ai) e [LeapSpace](https://www.elsevier.com/en-gb/products/leapspace). Conforme o registro da sessão de implementação, houve acesso inicialmente bloqueado por HTTP 403 no navegador de pesquisa e posterior observação em sessões autenticadas do Firefox, sem enviar perguntas nem abrir históricos ou documentos. Não há alegação de equivalência funcional, científica ou visual com esses produtos.

## Colors

O arquivo `argiloteca_custom/argiloteca/static/css/argiloteca-theme.css` é a fonte normativa dos tokens compartilhados; a tabela registra somente o subconjunto usado nesta superfície. Não cria outra fonte de verdade.

| Token herdado | Valor observado | Uso nesta interface |
| --- | --- | --- |
| `--arg-color-primary-strong` | `#6f4f34` | Identidade, ações, envio e citações |
| `--arg-color-primary-hover` | `#543a26` | Interação em ações e links |
| `--arg-color-accent` | `#e37f1d` | Linha sob o cabeçalho |
| `--arg-color-text` | `#2f2a24` | Texto principal |
| `--arg-color-muted` | `#665d53` | Descrições, instruções e metadados |
| `--arg-color-surface-page` | `#f5f2ec` | Fundo da conversa, herdado de `body` |
| `--arg-color-surface-soft` | `#f5f0e8` | Seleção de fonte, trechos e estados de controles |
| `--arg-color-border-soft` / `--arg-color-border` | alias / `#d7cabe` | Divisórias e histórico |
| `--arg-color-control-border` | `#968575` | Compositor, citações e ação de exemplo |
| `--arg-color-focus` | `#27666b` | Foco de teclado |

O CSS local usa branco nas superfícies de cabeçalho, compositor e fontes. A mensagem do usuário tem preenchimento local `#e9e0d3`; não foi promovido a token global. O laranja funciona como detalhe da marca, e o marrom concentra as ações.

## Typography

Títulos herdam `--arg-font-heading`: Catamaran, Lato, Helvetica Neue, Arial, sans-serif. Corpo e controles herdam `--arg-font-ui`: Lato, Helvetica Neue, Arial, sans-serif. O template pré-carrega Catamaran local e carrega o tema existente, sem introduzir outra família.

| Papel local | Medida observada | Aplicação |
| --- | --- | --- |
| Identidade | `1.55rem`, entrelinha `1.15`; `1.35rem` abaixo de 640px | Nome do assistente |
| Boas-vindas | `2.25rem`, entrelinha `1.15`; `1.8rem` abaixo de 640px | Pergunta inicial |
| Título de resposta | `1.6rem`, entrelinha `1.25` | Exemplo demonstrativo |
| Mensagens | Entrelinha `1.75` | Leitura da conversa |
| Entrada | `1rem`, entrelinha `1.6` | Mensagem digitada |
| Descrições auxiliares | Em geral `0.75–0.9rem` | Sessão, contagem e contexto |

## Layout

A aplicação ocupa `100dvh`, com fallback `100vh`: cabeçalho superior e região de trabalho com altura restante. A conversa tem rolagem própria e compositor inferior; o corpo da página não rola. A coluna de leitura limita mensagens a 760px, boas-vindas a 660px e região do compositor a 820px. Esses são valores locais observados, não uma escala de layout do repositório. A intenção de leitura até 72ch do brief não se traduz em uma regra `72ch` aplicada no CSS.

Com fontes abertas a partir de 900px, a grade reserva 350px à direita. Até 899px, as fontes usam `dialog.showModal()`, largura máxima de 390px e altura da janela; a conversa permanece em uma coluna. A mudança de largura reabre o painel na modalidade correta. Até 639px, o cabeçalho quebra em duas linhas, descrições visuais de ações cedem espaço aos ícones com nomes acessíveis, o compositor usa margens menores e considera a área segura inferior.

## Elevation & Depth

A superfície usa preenchimentos e bordas para separar conversa, controles e evidências. O CSS local não adiciona sombras nem animações decorativas. O diálogo móvel acrescenta um fundo escurecido (`rgb(47 42 36 / 30%)`) para indicar modalidade. Histórico usa popover nativo.

## Shapes

Controles principais usam cantos de 6px e compositor/histórico de 12px, coerentes com os valores existentes do tema, embora o CSS local declare esses valores diretamente. Citações e selo de protótipo usam 4px. A mensagem do usuário tem cantos de `12px 12px 3px 12px`. Fontes são linhas selecionáveis com divisórias; trechos aparecem em superfícies suaves, sem cartões elevados.

## Components

| Componente local | Comportamento e estados |
| --- | --- |
| Launcher | Link real para a rota, `rel="noopener"`; clique simples tenta popup nomeado `ArgiloClayRobo`, 1280×860, redimensionável, e zera `opener`. Se a abertura falhar, o link conserva a navegação normal. Dimensões e apresentação finais dependem do navegador. |
| Cabeçalho compacto | Mascote aprovado, nome, rótulo de protótipo, nova conversa, histórico, contador de fontes e seletor PT/EN existente. Ações principais têm altura mínima de 44px. |
| Boas-vindas | Três sugestões preenchem a entrada e dão foco; a ação de exemplo cria conversa demonstrativa própria. |
| Mensagens | Usuário e assistente têm autoria distinta. Entrada livre recebe confirmação fixa de protótipo; texto do usuário é inserido com `textContent`. O exemplo foi escrito localmente e é identificado como fictício. |
| Compositor | Campo rotulado de até 2.000 caracteres, contador e envio desabilitado quando vazio. Enter envia; Shift+Enter cria linha. `isComposing` preserva composição de texto. Foco visível no contêiner. |
| Citações e fontes | Dois marcadores no exemplo selecionam a fonte correspondente, abrem o painel e focam o trecho. Lista usa `aria-pressed`; botão de fontes usa `aria-expanded`. Ao fechar, o código recupera o foco da citação ou do controle de fontes conforme a ação. |
| Histórico | Popover de conversas da sessão; abre conversa anterior. Nova conversa mantém o histórico limitado localmente. |
| Copiar e exportar | Cópia usa Clipboard API com mensagem de sucesso/falha. Exportação gera `argiloclay-conversa.txt` localmente e inclui aviso de protótipo e fontes fictícias. |

A chave de armazenamento é `argiloclay-interface-session-v1`, em `sessionStorage`: até 12 conversas, com até 40 mensagens por conversa. A interface restaura a conversa após recarregar a página. Não há persistência no repositório. Se o armazenamento falhar, o uso continua em memória até recarregar, com aviso de falha na gravação. Não se deve tratar o histórico como arquivo permanente nem garantir sua restauração após fechar a sessão.

Há duas fontes fictícias: ficha da amostra ARG-DEMO-01 e pacote DRX ilustrativo da mesma amostra. Identificadores, campanha e nomes de arquivos são exemplos; nenhum RAW é processado. O link para o guia DRX é material de apoio, não prova de recuperação de uma fonte real.

O backend acrescenta apenas a rota de apresentação Flask (`GET /argiloclay`, endpoint `argiloteca.argiloclay_chat`) com `render_template`. O JavaScript da conversa não faz `fetch`, chamadas a modelo, recuperação ou gravação de registros. As traduções usam o fluxo Jinja/gettext e o seletor de idioma existentes.

## Do's and Don'ts

- Preservar a identidade, mascote, famílias de fonte e tokens do tema compartilhado.
- Manter a seleção de fonte ligada ao marcador exato da resposta e o comportamento modal em telas estreitas.
- Conservar avisos de demonstração na resposta, nas fontes e na exportação enquanto não houver integração real.
- Não transformar preenchimentos e medidas locais em regras globais sem uma decisão específica do produto.
- Não apresentar respostas fixas como geração de IA, exemplos como registros do acervo ou dois marcadores locais como recuperação RAG.
- Antes de conectar serviços, definir contratos e estados reais de processamento, indisponibilidade, ausência de evidências e persistência; esta entrega não os valida.

## Evidências e limites

As evidências existentes estão em `output/playwright/argiloclay-chat/`, relativo à raiz do projeto. A conferência documental não reexecutou nem alterou esses testes.

| Evidência | O que sustenta |
| --- | --- |
| `verification.json`, `verify.js` e `verification.log` | Oito cenários PT/EN em 320×740, 390×844, 768×1024 e 1440×900: composição independente, exemplo, citação correta, teclado, recarga, histórico, texto literal e ausência de overflow. Também registram mudança de modalidade, popup com `opener` nulo e ausência de erros/chamadas API/modelo monitoradas. A matriz usa fixtures HTML locais servidas em 5197, com assets provenientes da homologação; não equivale a oito testes ponta a ponta no servidor Flask. |
| `live-checks.json` | Rota real respondeu 200 em PT/EN com estrutura independente. |
| `welcome-1440.png`, `welcome-390.png`, `demo-1440.png`, `demo-390.png`, `source-390.png` | Estados visuais em português; não há capturas de todos os cenários da matriz. |
| `demo-export.txt` | Exportação demonstrativa local. Cópia e exportação foram exercitadas no cenário EN/1440 do script. |
| `.impeccable/review/argiloclay-chat-review.md` | Revisão independente, sem fixes materiais; aprovação restrita à interface demonstrativa. |

O responsável pela implementação também relatou observação do popup real no Firefox do usuário e exibição da captura na conversa, sem menus do repositório. Essa observação complementa os arquivos, sem substituir a matriz automatizada.

O detector não conseguiu resolver o template Jinja e deixou `design-detection.log` vazio. Esse arquivo não comprova ausência de defeitos. Foco, skip link, nomes acessíveis, status de ação e modalidade têm suporte no código, mas não houve certificação integral de contraste computado ou teste com leitor de tela. Não foram avaliados qualidade científica, identificação mineralógica, modelo, recuperação, citações reais, segurança integral ou integrações futuras.

Arquivos de implementação sob `argiloteca_custom/argiloteca/`: `templates/semantic-ui/argiloteca/argiloclay_chat.html`, `templates/semantic-ui/argiloteca/argiloclay_robo.html`, `static/css/argiloclay-chat.css`, `static/js/argiloclay-chat.js`, `static/js/argiloclay-launcher.js` e a rota de apresentação em `views.py`. A documentação não modifica esses arquivos.

## Acesso em tela cheia

O cabeçalho da conversa inclui o botão com ícone de início “Voltar ao acervo” / “Back to repository”, apontando à página inicial. O rótulo fica visível no celular e a barra de ações permite quebra de linha. Oito cenários PT/EN de 320 a 1280 px foram verificados em `output/playwright/argiloclay-back-link/`, sem overflow ou ocultação do campo de mensagem.

O launcher compartilhado acompanha o elemento nativo de tela cheia e os painéis DRX/pacote analítico que usam fallback CSS. O mesmo link é movido e restaurado à posição original, preservando seus eventos e a abertura da conversa independente. Não duplicar o launcher nem tentar resolver a tela cheia nativa somente aumentando `z-index`: elementos externos ao alvo não são renderizados nesse modo.

Em 19/10/2026, passaram 12 cenários Chromium (comparador, análises e pacote analítico; 1440/390 px; tela cheia nativa/CSS), cobrindo visibilidade após rolagem, teclado, popup independente e restauração sem duplicação. Evidências e limites em `output/playwright/argiloclay-fullscreen/README.md` e `verification.json`. São testes do acesso ao assistente em cópias públicas das páginas com assets da homologação; não validam carregamento científico nem sessão autenticada do Firefox.

### Preferência de área científica expandida

`scientific-fullscreen.js` conserva a preferência por aba entre Análises e DRX com as classes CSS existentes. A Fullscreen API é solicitada no clique inicial, mas o modo CSS continua quando o navegador encerra a camada nativa para navegação ou seleção de arquivo. O controle “Sair da tela cheia” limpa a preferência e recolhe o painel. A barra do navegador pode reaparecer: não se garante fullscreen do sistema operacional entre documentos. Ao sair para uma página sem painel científico, a preferência é encerrada.

Launcher v4 abre um popup novo sem reutilizar abas nomeadas e guarda sua referência por página. Ao abrir a conversa a partir da Fullscreen API, sai da camada nativa antes de abrir a janela, mantendo o painel CSS expandido. Evidências em `output/playwright/scientific-fullscreen/`: quatro cenários de navegação/arquivo temporário, dois de popup nativo e observações do Firefox real, com limites explicitados no README.

### Comparação preservada entre Análises e DRX

Em 20/10/2026, `scientific-session.js` passou a conservar o espaço de trabalho em IndexedDB, com identificador por aba em sessionStorage e escopo de conta. Inclui curvas, metadados/proveniência e arquivos temporários originais, além dos ajustes do gráfico. A lista de análises conserva seleção e filtros. Links entre os dois módulos e o botão de comparação aguardam a carga pendente e a transação local; amostras novas são acrescentadas à comparação existente. Remover/limpar continua explícito, e uma URL anterior não repõe itens descartados na recarga.

Não cria depósitos ou publicações no Invenio. A preservação exige que a aba já esteja executando a interface atualizada; não recupera variáveis de abas antigas. Evidências em `output/playwright/scientific-session/README.md` e `verification.json`: fluxos completos Chromium em 1440/390 px, integridade dos arquivos e curvas, zoom X/Y, marcadores, seleção, filtros, novas amostras, remoção/limpeza, histórico, isolamento por aba, modo expandido e falha de armazenamento. Teste autenticado de persistência no Firefox e suíte backend pytest não foram executados nesta entrega; limites estão registrados no relatório.
