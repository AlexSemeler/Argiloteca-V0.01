# Remover e arquivar no Mac

A administração oferece **Remover e arquivar** em **Povoamento** e em **Conectar ao Acervo**. Endereço local: `https://127.0.0.1:5101/administration/maintenance/?ln=pt`.

## Fluxo

1. Escolha **Registros e vínculos**, **Histórico de importações** ou **Lotes no Mac**.
2. Localize o item, selecione a operação e informe uma justificativa.
3. Clique em **Ver prévia**. Confira destino, efeitos, arquivos e eventuais dependências.
4. Confirme a operação. Para exclusão definitiva, digite também **EXCLUIR**.
5. Acompanhe o resultado e baixe o ZIP em **Auditoria e backups**.

A consulta e a prévia não alteram registros. A confirmação cria uma tarefa persistente. Antes de alterar, o worker confere novamente a prévia, as permissões e as dependências e verifica um backup. Mudanças posteriores à prévia bloqueiam a execução. O mesmo pedido confirmado não cria outra aplicação.

Para um rascunho com a única operação `delete_draft`, o formulário mostra **Excluir rascunho**, mantém a justificativa obrigatória e oferece o botão vermelho com lixeira **Excluir rascunho — ver prévia**. A ação é enviada em campo oculto, sem seletor redundante. A ajuda associada ao botão explica a confirmação na próxima tela e a verificação do backup; o botão abre a prévia. A confirmação final continua exigindo **EXCLUIR** e checkbox, com o mesmo fluxo de backup e auditoria.

## Operações disponíveis

| Item | Operações e alcance |
| --- | --- |
| Rascunho | Exclusão definitiva pelo serviço nativo, com metadados e arquivos no backup. Descartar uma edição não apaga a publicação correspondente. |
| Publicação | Retirada e restauração da versão selecionada, ou exclusão definitiva com prévia e backup integral. A retirada usa o motivo nativo `retracted` e mantém metadados e arquivos. A purga remove os metadados, revisões e arquivos exclusivos. |
| Comunidade | Remove somente o vínculo selecionado. As outras comunidades, propriedade, acesso, metadados e arquivos permanecem. A remoção da comunidade padrão elimina a indicação de padrão. |
| Conexão científica | Remove somente a conexão e a referência gerada por ela, mantendo citações anteriores e o destino. |
| Associação DRX | Marca o vínculo como removido, registra o evento e atualiza o pacote de metadados; preserva RAW, análises e registro. |
| Localização | Remove latitude e longitude do item escolhido; mantém as demais informações e localizações. |
| Histórico | Arquiva e restaura tarefas sem repetir a importação. Exclui definitivamente somente tarefas sem dependentes, claims DOI/OpenAlex ou backups próprios. |
| Lote V59 | Arquiva em `.admin-trash`, restaura ou exclui definitivamente os arquivos de um lote. Mantém os registros já importados e o backup administrativo. |

**Purga de publicações:** a extensão local implementa a operação sobre os modelos, permissões e armazenamento nativos, pois `purge_record()` do InvenioRDM 14 instalado não está implementado. Pode excluir uma publicação ativa, retirada ou marcada para purga, desde que tenha somente uma versão e nenhuma edição pendente. Outras versões e dependências bloqueiam a operação; não há exclusão em cascata de registros relacionados. Os vínculos da publicação com comunidades são removidos, mas as comunidades permanecem.

A prévia informa o inventário de binários e os arquivos compartilhados. O ZIP inclui os metadados, revisões históricas, arquivos de mídia e objetos das áreas de armazenamento selecionadas. Cada binário tem tamanho e checksum verificados antes da remoção. Arquivos ainda referenciados por outro objeto nativo são preservados. Identificadores locais permanecem reservados, e DOIs externos não são cancelados.

## Dependências e preservação

A retirada/exclusão de registro é bloqueada quando há conexões científicas, associações DRX ativas, referências de outros registros ou solicitações vinculadas. Uma edição em rascunho bloqueia alterações na publicação. Resolva os vínculos e gere outra prévia. Os claims de identidade DOI/OpenAlex são preservados para impedir recriação acidental do item removido pelo importador. Quando um registro legado tem DOI/OpenAlex sem claim, a remoção também reserva essa identidade na mesma transação; claims existentes não são substituídos.

Antes de arquivar/excluir um lote, arquive suas revisões pendentes e aguarde as tarefas ativas. Durante manutenção confirmada, nova preparação/importação desse lote fica bloqueada. O agente local executa somente operações literais de manutenção em diretórios `v59_*`, sem links simbólicos. Não substitui um destino existente.

## Backups e auditoria

Os ZIPs guardam a prévia, responsável, justificativa e estado anterior. Remoção de rascunho/retirada inclui os binários originais e seus checksums; alterações de vínculos guardam os metadados anteriores, pois seus arquivos não mudam. Lotes têm manifesto de todos os arquivos e SHA-256. O backup precisa ser válido antes da operação. A auditoria de manutenção e seus backups são protegidos contra exclusão pela própria interface.

Os backups ficam na fila configurada (`ARGILOTECA_OPENALEX_QUEUE`), em `duplicate-backups` (registros/históricos) e `maintenance-backups` (lotes), salvo configuração específica de `ARGILOTECA_OPENALEX_BACKUPS`. O download administrativo verifica SHA-256 e exige acesso de administrador. As respostas são privadas e sem cache; operações POST exigem CSRF.

Arquivar possui restauração pela interface. Exclusão definitiva não possui restauração automática: o ZIP continua disponível para recuperação administrativa assistida. Backups e auditoria não são apagados junto com o item. Se os metadados de uma publicação já foram eliminados e a limpeza de índices ou binários falhar, a tela informa esse estado e oferece **Concluir limpeza da purga** para retomar a mesma tarefa. O checkpoint conserva as informações necessárias à limpeza mesmo após a remoção das linhas dos arquivos. Não gere outra exclusão para esse caso.

O agente `br.argiloteca.openalex-host` deve estar ativo para operações em lotes no Mac. Um pedido já enviado não é repetido; após interrupção do agente, confira o estado real e o backup antes de preparar outra prévia. Os links funcionais das seções Povoamento e Conectar o acervo usam botões com ícones SVG e rótulos visíveis, mantendo navegação e ações destrutivas identificadas pelo texto.
