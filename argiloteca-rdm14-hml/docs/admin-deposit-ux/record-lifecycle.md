# Blocos públicos do ciclo de vida dos dados

Atualização de 19/10/2026: o bloco completo começa recolhido. O título aciona
o acordeão nativo `.ui.accordion`, inicializado pelo tema Invenio já carregado
nos registros. A marcação segue `.title`, `.trigger` e `.content`, sem novo
controlador JavaScript. Um botão nativo permite clique, Enter e Espaço;
`aria-controls`, `aria-labelledby` e o estado `aria-expanded` acompanham a
abertura e o fechamento. Os dados continuam públicos para consulta ao expandir.

Validação desta atualização: registro público `55117-a8656` com HTTP 200 em
PT/EN e CA local validada. Seis cenários Playwright, em 320/390/1440px, com
conteúdo e links idênticos à captura anterior, estado inicial fechado,
interação por clique/teclado, fechamento após recarga e sem transbordamento
horizontal ou exceções JavaScript. Evidências em
`output/playwright/lifecycle-accordion/`. Não houve gravação de registros.

Refinamento Impeccable em 18/10/2026, seguindo o grid de títulos e conteúdo do
componente nativo `invenio_app_rdm/records/details/details.html`.

- Seções com títulos à esquerda e divisórias simples, sem etapas duplicadas.
- Pares de rótulo/valor alinhados, textos longos com quebra, fonte Lato existente.
- No celular, títulos, rótulos e valores se empilham na ordem de leitura.
- Blocos sem cartões aninhados ou coluna lateral reservada para números.
- Painéis de gráficos vazios não reservam espaço; tabela química e payload
  original permanecem. Não foi implementado um novo renderizador de gráficos.
- Dados, links, avisos de curadoria, popups e seletor de amostras preservados.
- Ações científicas continuam reservadas a usuários com permissão de edição.

Validação: conteúdo renderizado antes/depois idêntico em en/pt, desconsiderando
somente rótulos de etapa removidos. Dezesseis casos Playwright em prévias reais
do runtime, 320/390/768/1440px, sem overflow ou exceções JavaScript; seletor de
amostras exercitado. Resposta HTTPS pública real da homologação conferida com
CA validada. Nenhuma alteração de registros, permissões ou backend científico.

Evidências, comparadores, capturas e limites do ambiente de prévias:
`output/playwright/lifecycle-layout/` na raiz do workspace. O mapa lateral do
registro sintético completo retornou HTTP 500 durante o teste; não é parte
da seção refinada nem foi alterado nesta tarefa.
