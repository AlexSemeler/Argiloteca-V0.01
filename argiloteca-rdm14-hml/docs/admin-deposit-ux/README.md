# Administração e depósito científico: organização de UX

Refinamento com Impeccable em 18/10/2026. A identidade marrom e a página inicial
restaurada são preservadas. `/uploads/new` fornece a referência estrutural.

## O que mudou

- Administração com menu lateral por área, links agrupados no painel, retorno ao
  acervo, idioma e conta. A visibilidade continua determinada por `item.visible`
  e pelas permissões nativas. Versões técnicas ficam em uma seção recolhível.
- Os templates base atendem listas, criação, detalhes e edição nativos. Botões
  longos das tabelas quebram linha; os componentes React e ações são preservados.
- Depósitos geral e científico compartilham breadcrumb, título e abas. Depois
  de salvar o científico, seus links apontam para o mesmo ID no depósito nativo.
- Depósito científico com informações básicas convencionais, editor de autores,
  seções recolhíveis, conteúdo e coluna de ações na proporção 11/5 do nativo.
- Relações pesquisa de campo → amostra → análise com orientação junto aos campos
  e sugestões dos IDs já presentes. Valores livres continuam permitidos e são
  validados pelo serviço. Ausente, nulo, zero e valores adicionais são preservados.
- A interface impede pedidos simultâneos de salvamento, avisa antes de sair com
  alterações e mostra uma confirmação antes da publicação. Erros exibem caminhos
  compreensíveis e levam ao campo correspondente; os detalhes originais permanecem.

## Arquivos

`templates/semantic-ui/invenio_administration/` contém os overrides de apresentação.
O prefixo `argiloteca_admin_native` permite herdar do pacote instalado sem copiá-lo.
`templates/semantic-ui/argiloteca/deposit_navigation.html` é a navegação compartilhada.
`argiloteca-workflows.css` cuida das duas áreas; `scientific-metadata.css` e
`scientific-metadata.js` cuidam do editor. O menu progressivo usa
`argiloteca-workflows.js`, carregado uma vez pelo bloco JavaScript da página.

## Verificação e limites

Evidências na raiz do workspace: `output/admin-deposit-ux/`.
Os links administrativos foram abertos na sessão existente do usuário no Firefox:
registros, rascunhos, comunidades, tipos de vocabulário, páginas, banners,
domínios, conjuntos OAI-PMH, usuários, solicitações, moderação e processamento.
Os depósitos geral e científico e a troca en/pt foram conferidos nessa sessão.
Nenhuma ação administrativa, exclusão ou publicação foi executada.

Playwright utiliza prévias isoladas renderizadas com os templates reais e
fixtures explicitamente sintéticas: en/pt × 1440/768/390/320 nas duas superfícies.
Salvamento e erros são simulados; conferem o contrato enviado, CSRF, preservação
de tipos/valores e os links do mesmo ID, sem gravar dados no banco. Conferem ainda
modo somente leitura, foco de erro, confirmação de publicação e menu com Escape.
Não são prova de uma nova publicação/persistência integrada nem certificação WCAG.
O backend científico, os schemas, os índices e as permissões não foram alterados.

Os arquivos estão ativos pelos volumes da homologação. Web UI/API foram
reiniciados e o Nginx foi recarregado para resolver os endereços dos serviços.
Não foi construída uma nova imagem nesta tarefa. Uma compilação futura deve
incluir os arquivos. Backups desta alteração estão em `output/admin-deposit-ux/before/`.

## Validação integrada posterior do rascunho

Em 18/10/2026, a pedido do usuário, foi criado e salvo pela interface real do
Firefox o rascunho sintético `sz134-yzy87`. Após navegar ao formulário nativo e
reabrir o editor científico, título, data, autor, descrição e relações
campanha → amostra → análise permaneceram corretos. Zero, nulo explícito,
ausência e acentos foram preservados. Uma leitura SQL independente confirmou
a correspondência exata dos campos científicos e a ausência de versão publicada.
Nenhuma publicação foi solicitada. Evidências e verificador somente leitura em
`output/playwright/scientific-draft-roundtrip/`, na raiz do workspace. Essa
verificação integrada complementa os testes isolados anteriores; foi operada
no Firefox por Computer Use, sem reutilizar credenciais no Playwright.

## Ações científicas nos registros públicos

Em 18/10/2026, os atalhos Metadados científicos e Argiloteca XML passaram a
aparecer apenas para usuários autenticados com `permissions.can_edit`, seguindo
a permissão nativa de edição do Invenio. A seção científica na própria página
continua pública e somente de leitura. Na consulta científica separada, a ação
Iniciar edição também depende da permissão nativa de editar o registro.
O exemplo `55117-a8656` foi conferido anonimamente por HTTPS e no Firefox;
evidências e matriz de visibilidade do template estão em
`output/playwright/record-scientific-actions/` na raiz do workspace.


## Refinamento CPAA em 19/10/2026

Catamaran nos títulos e summaries, detalhes laranja #e37f1d nos separadores e botões principais marrons também nos fluxos administrativos e científicos. A confirmação de publicação e as relações do formulário não mudaram. Evidências de 24 cenários PT/EN e celular/tablet/desktop em `output/playwright/cpaa-workflows/` na raiz do checkout; páginas protegidas renderizadas em contexto isolado com fixtures sintéticas, sem nova autenticação nem operações de escrita. Botão da equipe retirado do rodapé compartilhado por pedido posterior; contatos e logos preservados.
