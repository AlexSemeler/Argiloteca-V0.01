# Importação OpenAlex na administração local

Acesso: <https://127.0.0.1:5101/administration/openalex/?ln=pt>.
É necessário entrar com a conta administrativa existente. O menu **Povoamento →
Importação OpenAlex** leva ao mesmo módulo.

## Operação

1. Em **Lotes disponíveis**, selecione **Preparar revisão**. Limite `0` prepara
   todas as obras; `1` permite um teste. Lotes incompletos não são importáveis.
2. Abra o título para inspecionar metadados, alertas, dados originais e campos
   omitidos. Correções são objetos JSON de campos de `metadata`; por exemplo,
   `{"title":"Título conferido","languages":[{"id":"por"}]}`. Autores devem
   seguir a estrutura nativa de `creators`; listas substituem a lista inteira.
   A correção gera outra revisão e preserva a anterior.
3. Selecione os registros aptos da página, confirme a revisão e escolha
   **Importar e atualizar selecionados**. Cada página mostra até 20 obras;
   a seleção pertence à página atual. Alertas continuam disponíveis para curadoria.
4. Abra os rascunhos pelo resultado da tarefa. Correspondências por DOI ou OpenAlex
   sobrescrevem os campos bibliográficos fornecidos no mesmo registro. Se já
   estiver publicado, o serviço nativo abre ou reutiliza um rascunho de edição
   com o mesmo PID; não cria outra versão ou registro. A publicação das mudanças
   segue pelo depósito nativo, após curadoria.
5. Em **Nova extração**, escolha um termo ou todos os termos e os limites.
   O V59 faz correspondência textual; `max_terms` limita termos correspondentes,
   não o total de obras. O máximo é 100 termos × 100 resultados. Para testar,
   use caulinita, 1 resultado, 1 termo e deslocamento 0.
6. Acompanhe a coleta na tarefa e clique **Preparar este lote** ao concluir.
   Histórico, relatórios JSON com proveniência e CSV ficam na administração.
   A interface preserva o idioma nas ações e filtros; mensagens provenientes do
   conversor legado são mantidas em seu idioma original.

## Integração executada

- A aplicação e o worker continuam nos containers InvenioRDM locais.
- `povoamento/openalex` é montado com o mesmo caminho absoluto do Mac, somente
  para leitura. Assim os manifestos históricos continuam válidos.
- O agente `scripts/openalex-host-agent.py` executa o V59 no Python do Mac,
  usando seu launcher, venv e credencial existentes. Não abre porta HTTP.
- Web e agente compartilham apenas a fila `data/openalex-admin-queue`.
  Pedidos, checkpoints, resultados e heartbeat são escritos atomicamente.
- `docker-compose.openalex.yml` configura `ARGILOTECA_OPENALEX_ROOT` e
  `ARGILOTECA_OPENALEX_QUEUE` em UI, API, worker e scheduler.
- O scheduler local existente preserva seus jobs nativos e o sincronismo RAG;
  acrescenta a recuperação OpenAlex a cada 30 segundos.
- `argiloteca_openalex_job` guarda responsável, parâmetros, revisão, hashes,
  proveniência, resultados e checkpoints. `argiloteca_openalex_claim` liga
  DOI/OpenAlex ao rascunho criado. São duas tabelas adicionais, sem migração
  dos registros nativos.

Os adaptadores conferem os arquivos e hashes das instalações prontas. O
conversor `invenio_metadata.py` e o leitor `lote_inputs.py` são carregados da
instalação íntegra selecionada. Não foram alterados os arquivos das versões
V59 ou metadados_v1, seus PRONTO.json ou lotes preexistentes.

A revisão persistida no banco é o pacote administrativo: preserva a mesma
normalização, agrupamento, alertas e proveniência do processo de Terminal.
Pacotes antigos em `processos/metadados_invenio/pacotes` continuam disponíveis
pelo processo original; na interface, prepare o lote de origem correspondente.
PDFs não integram este módulo: `files.enabled=false`.

## Metadados, atualização e deduplicação

A revisão aplica o conversor bibliográfico e o schema da instância instalada.
Campos científicos inferidos, idioma inglês imposto pelo V58 e licenças não
comprovadas não viram afirmações bibliográficas. Dados omitidos permanecem na
proveniência. DOI principal existente permanece externo; nenhum DOI é registrado.
Obras sem DOI precisam de identidade OpenAlex válida e dos campos obrigatórios.

A deduplicação percorre o banco nativo, incluindo rascunhos, e compara
identidades estruturadas normalizadas. Não depende de paginação parcial ou da
atualização do índice de busca. Múltiplos registros para a mesma identidade
bloqueiam a revisão. Falhas no inventário impedem a criação.

Um lock por tarefa impede execução simultânea por dois workers. Um lock
transacional comum serializa criação e consulta de claims entre importações.
O rascunho criado ou atualizado, as claims e o checkpoint são confirmados na mesma transação
PostgreSQL. Uma falha antes do commit desfaz os três; após o commit, a retomada
reutiliza o checkpoint, sem reaplicar a sobrescrita. Cada atualização guarda
os metadados anteriores e a revisão nativa no resultado da tarefa. Claims de registros excluídos são conservadas para
impedir recriação silenciosa. Essa exclusão intencional exige curadoria, não
um botão para ignorar duplicatas.

Desde o ajuste de sobrescrita, o resultado distingue **criado** de **atualizado**.
Uma correspondência única nunca chama o serviço de criação: utiliza `edit()` e
`update_draft()` no PID existente. Não existe fallback para criar outro registro
quando a atualização falha. Se houver dois PIDs diferentes para a identidade,
a tarefa exige resolver o conflito antes de sobrescrever.

Os campos de `metadata` fornecidos pelo lote substituem os respectivos valores
anteriores; campos ausentes no lote continuam preservados. Identificadores são
reunidos para conservar aliases de deduplicação. Arquivos, campos científicos,
acesso, propriedade e comunidades existentes são preservados. Um DOI já
atribuído mantém seu provider nativo; DOIs conflitantes bloqueiam a operação.
A lista de campos e valores anteriores fica no relatório JSON administrativo.

Execuções antigas que exibem “Já existe” mantêm o resultado histórico. Submeter
a seleção novamente utiliza a política de sobrescrita; a assinatura da tarefa
inclui a versão da política, impedindo que um resultado antigo seja reutilizado
como se fosse uma atualização nova.

O lock cobre importações deste módulo. Uma criação manual simultânea, feita
fora do módulo, não participa desse protocolo. Para cargas concorrentes por
outros importadores, coordene as execuções ou adote uma política de unicidade
comum ao repositório.

## Ativação e reinício no Mac

Diretório da aplicação:
`/Users/alexandresemeler/Argiloteca/homologacao/inveniordm-14.0.4/argiloteca-rdm14-hml`.

Para reaplicar volumes, tabelas adicionais e recursos estáticos, preservando os
outros overlays já ativos:

```sh
bash scripts/openalex-local
```

Na primeira ativação, confirme que os serviços voltaram a ficar saudáveis antes
de acessar a página. O script não altera o banco de produção.

O agente foi ativado no domínio do usuário do launchd com o label
`br.argiloteca.openalex-host`. A configuração fica em `~/Library/LaunchAgents/br.argiloteca.openalex-host.plist`,
com uma cópia na fila. O agente inicia automaticamente ao entrar na sessão
do Mac. Para instalá-lo ou recarregá-lo, execute da raiz do repositório com um
Python local >=3.10:

```sh
/caminho/para/python3 argiloteca-rdm14-hml/scripts/install-openalex-host-agent.py
```

Pode usar o Python da instalação V59 íntegra, como nesta homologação:

```sh
povoamento/openalex/instalacoes/v59_20261017_125308_bzyfa6e2/.venv/bin/python3 argiloteca-rdm14-hml/scripts/install-openalex-host-agent.py
```

O instalador gera um plist com o Python que o executa e preserva configurações
preexistentes de outro agente com o mesmo nome. Não instala pacotes
em ambientes existentes. O agente tem limite de 20 minutos por coleta; lotes
parciais permanecem para diagnóstico. Ao interromper uma coleta no Mac, o
checkpoint impede repeti-la silenciosamente. **Retomar tarefa** de extração
cria uma nova tentativa no histórico.

Para interromper o agente na sessão atual (o plist continua instalado):

```sh
launchctl bootout "gui/$(id -u)/br.argiloteca.openalex-host"
```

## Diagnóstico e retomada

- Agente offline: verifique `data/openalex-admin-queue/heartbeat.json` e
  `agent.stderr.log`, depois recarregue o agente.
- Tarefa na fila: verifique worker, scheduler e RabbitMQ locais. A recuperação
  reenvia tarefas ainda pendentes; o lock descarta entregas concorrentes.
- Falha: consulte a tarefa e o log do worker. Rascunhos já criados aparecem no
  checkpoint. **Retomar tarefa** não os recria. A conta responsável precisa
  continuar ativa e administradora.
- Lote alterado ou hash divergente: prepare outra revisão; não edite os payloads
  de uma revisão esperando que a importação aceite a mudança.
- Alteração do conversor instalado: reinicie os workers antes de continuar.

Permissões administrativas são verificadas em todas as rotas, inclusive
relatórios. Escritas exigem CSRF. Credenciais permanecem no servidor/Mac;
relatórios e HTML não contêm a chave OpenAlex ou token pessoal da Argiloteca.

## Validação da versão inicial em 23/10/2026

- 16 testes automatizados: leitor/conversor reais, proveniência, hash alterado,
  caminhos e symlinks, instalação alterada, lote incompleto, correções,
  DOI com pontuação, obra sem DOI, limites de coleta, autorização, CSRF,
  vocabulário inválido na instância, conflitos de duplicatas e falha de inventário.
- Navegador real: iniciar coleta de caulinita, preparar lote, revisar, selecionar,
  importar e abrir o depósito nativo.
- Coleta real pelo agente: lote `v59_20261023_175906_ysygyvwd`, 1 publicação,
  chamada autenticada ao OpenAlex confirmada pelo V59.
- Fixture identificada: `v59_20261023_integracao_sintetica`. Seu identificador
  OpenAlex é fictício. Criou somente o rascunho restrito `9yar7-1w110`, propriedade
  do administrador, sem erros nativos e sem publicação.
- Nova tarefa com a mesma identidade: 0 criados e 1 duplicata.
- Duas tentativas de lock da mesma tarefa: somente a primeira entrou.
- Falha simulada após flush e antes de commit: nenhum rascunho ou claim adicional.
- Retomada após checkpoint confirmado: nenhuma duplicação.
- Lote real anterior reconhecido como publicação existente `ymaw7-7zw86`.

Evidências e scripts da execução ficam em `output/openalex-admin-20261023`
na raiz do repositório. Não foi executada importação integral dos dois lotes
históricos com 5.763 linhas cada.

Reexecutar os testes unitários, da raiz do repositório:

```sh
docker exec -i argiloteca-rdm14-hml-web-ui-1 python - < argiloteca-rdm14-hml/argiloteca_custom/tests/openalex/test_openalex.py
```

O verificador integrado requer explicitamente o ID da importação da fixture
sintética restrita e acrescenta tarefas de teste ao histórico:

```sh
docker exec -i argiloteca-rdm14-hml-web-ui-1 python - --import-job 9cbc72a04250482f93b0f502f951c9fe < argiloteca-rdm14-hml/scripts/verify-openalex-native.py
```


## Validação da sobrescrita

O ajuste acrescentou nove testes ao conjunto anterior (25 ao todo), cobrindo
substituição dos campos fornecidos, preservação da curadoria, aliases, provider
DOI, complementação de DOI, conflito de identidade e alvo excluído.

O verificador integrado de sobrescrita altera somente o rascunho sintético
restrito. Confirma o mesmo PID e a mesma contagem de registros, os valores
sobrescritos persistidos, o snapshot anterior e a preservação de campos
científicos, arquivos, acesso e responsável. Testa também rollback de atualização,
retomada e conflito entre correspondências. O teste opcional de publicado edita
no mesmo PID dentro de uma transação explicitamente desfeita; não persiste
mudanças na publicação real.

```sh
docker exec -i argiloteca-rdm14-hml-web-ui-1 python - --import-job 9cbc72a04250482f93b0f502f951c9fe --published-test-id ymaw7-7zw86 < argiloteca-rdm14-hml/scripts/verify-openalex-upsert.py
```

## Consolidação dos duplicados existentes em 23/10/2026

A auditoria percorreu o banco inteiro, agrupando identidades DOI/OpenAlex
normalizadas entre registros independentes. Versões e rascunhos do mesmo
registro não foram contados como duplicatas; publicações retiradas e seus
rascunhos antigos foram excluídos da população ativa.

Foi encontrado um único par ativo, DOI `10.2136/sssabookser7.c9`, título
**Allophane and Imogolite**. O registro `2wj4w-c9b76` foi mantido por ser mais
antigo e já pertencer à comunidade **Alofana e Imogolita**. Recebeu os dados
minerais mais completos de `4tj7c-z7740`: fórmulas, sistema cristalino da
alofana, descrições, ambientes de formação e datas de sincronização. Os
metadados bibliográficos eram idênticos. Os dois registros não tinham anexos
nem arquivos de mídia, portanto não foi necessário transferir arquivos.

A atualização foi publicada no mesmo PID e na mesma versão. A duplicata
foi retirada pelo serviço nativo de exclusão lógica, com motivo `duplicate`
e nota indicando o registro principal. Os dados anteriores permanecem no
banco e no backup. Não havia referências em outros registros, pedidos ou
vínculos DRX para migrar. O importador passou a ignorar rascunhos retidos
de publicações retiradas; claims históricos continuam protegendo identidades.

A operação usou backup PostgreSQL validado, snapshots anteriores, lock
compartilhado com a importação e revisão nativa. O ensaio integral foi desfeito
antes da execução real. Esse ensaio também confirmou que um rascunho de edição
retido da duplicata não reaparece no inventário. A aplicação real e a retirada
ocorreram na mesma transação nativa, preservando proprietário, acesso,
comunidade e identificadores. Rótulos de idioma e tipo de publicação são
resolvidos pelo vocabulário nativo a partir dos mesmos IDs.

Após a operação: **1.329 registros independentes ativos e zero grupos
duplicados**. A busca por esse DOI retorna somente `2wj4w-c9b76`; a página
principal responde HTTP 200 e a retirada HTTP 410, com referência ao principal.
Os 25 testes do importador passaram. Evidências privadas, hash SHA-256 e backup
ficam em `output/openalex-deduplication-20261023/` na raiz do repositório.

O script `scripts/consolidate-openalex-duplicates.py` exige snapshot anterior
e IDs explícitos. Seu padrão é ensaiar e desfazer. Ele recusa pares com arquivos,
edições pendentes, versões posteriores ou diferenças bibliográficas não
revisadas; não é um eliminador automático de registros.

## Verificação e consolidação pela administração

O menu **Povoamento → Duplicados DOI/OpenAlex** abre
`/administration/openalex/duplicates/`. A operação administrativa aceita
registros publicados, rascunhos e grupos mistos, inclusive com anexos e mídia.

1. **Verificar duplicados** consulta o banco em uma tarefa de segundo plano.
   Versões e edições do mesmo registro são agrupadas pelo parent; retirados
   não entram na população ativa. A consulta não depende do índice de busca.
2. **Comparar e preparar prévia** mostra todos os candidatos, metadados e
   arquivos. O principal sugerido prioriza publicação, DOI gerenciado,
   comunidades e completude, com desempate pelo registro mais antigo.
3. Escolha o principal e confira as alternativas dos campos divergentes.
   Campos ausentes são preenchidos e listas são combinadas. Para textos,
   o mais longo é apenas uma sugestão; é possível preservar o texto curado
   mais curto. **Salvar prévia com estas escolhas** cria outra revisão e
   ainda não altera os registros. Trocar o principal recalcula as sugestões.
4. Confira a prévia dos campos e o destino de cada arquivo. Conteúdos
   diferentes com o mesmo nome recebem nomes distintos. Conteúdo idêntico
   no mesmo destino é mantido uma vez, mas todos os originais entram no backup.
5. Confirme **Criar backup e consolidar este grupo**. O worker valida novamente
   identidades, vínculos, revisões e permissões. Se qualquer registro mudou,
   a operação exige outra verificação. Falha de backup impede a consolidação.
6. Baixe o ZIP pelo resultado ou pelo histórico. O principal publicado mantém
   PID e versão; um principal em rascunho continua sem publicação. Duplicatas
   publicadas recebem exclusão lógica com referência ao principal. Rascunhos
   excedentes são removidos pelo serviço nativo depois da preservação dos dados.

O ZIP inclui o plano aprovado, snapshots serializados, JSON nativo de registros
e parents, todos os binários originais e manifesto SHA-256. Checksums nativos,
tamanhos, integridade ZIP e SHA-256 são conferidos antes da alteração; os
arquivos do principal são conferidos novamente antes de retirar os excedentes.
As cópias usam o mecanismo nativo ObjectVersion/FileInstance, preservando
conteúdo, metadados de arquivo e tags, sem substituir arquivos existentes.
No Mac, os backups persistem em
`argiloteca-rdm14-hml/data/openalex-admin-queue/duplicate-backups/`, com acesso
administrativo autenticado ao download e permissões restritas no disco.

Conflitos de DOI, responsáveis, acesso/embargo, comunidades não preserváveis,
edições pendentes, histórico de versões, solicitações e referências externas
ao grupo bloqueiam a consolidação até revisão. Vínculos DRX e colisões de
arquivos RAW também exigem seu fluxo próprio, preservando nomenclatura e
proveniência científica. Claims DOI/OpenAlex são transferidos ao principal;
repetições do formulário e entregas repetidas da tarefa não refazem a operação.

## Classificador de comunidades na importação

Novas revisões de lotes mostram a coluna **Comunidades**. O classificador
reutiliza o vocabulário íntegro do extrator V59 e o mapeamento existente em
`argiloteca.mineralogia.COMMUNITY_SLUG_BY_GROUP_KEY`, consultando somente
comunidades ativas e com permissão administrativa de inclusão direta.

Há correspondência por palavras completas nos títulos, descrições e assuntos,
em português e inglês, com normalização de acentos e pontuação. Termos
compostos específicos prevalecem sobre seus componentes no mesmo trecho:
`illite-smectite` leva aos interestratificados. Temas independentes podem
propor mais de uma comunidade. Na ausência de evidência textual preservada,
o termo controlado da extração é usado e identificado como tal na proveniência.
Não há associação por título de periódico, aproximação parcial ou comunidade
genérica inventada para os casos sem correspondência.

Confira os destinos propostos, desmarque os inadequados e execute **Importar,
atualizar e classificar**. A associação ocorre na mesma transação do rascunho
e do checkpoint de importação, pelo vínculo nativo do parent. Os vínculos
anteriores são mantidos, sem duplicação ou transferência de propriedade.
O relatório final mostra apenas as comunidades efetivamente confirmadas nesta
importação; sugestões originais continuam identificadas no detalhe.
Novos rascunhos permanecem sem publicação; registros existentes continuam
com o mesmo PID. A publicação posterior preserva as comunidades selecionadas.

Termos sem destino conhecido, comunidades desativadas ou sem permissão ficam
sinalizados para revisão; podem ser importados sem nova comunidade. Revisões
anteriores ao classificador devem ser preparadas novamente para obter sugestões.
O detalhe de cada publicação mostra termos, campos de origem, versão das regras
e hashes do vocabulário e mapa usados. A classificação é bibliográfica temática:
não cria amostras, resultados analíticos ou inferências de identificação mineral.

As validações desta implementação incluem 46 testes unitários, rotas com
autorização e CSRF, download privado e rejeição de backup divergente, consolidação
nativa com cinco anexos e colisões de nomes, dois arquivos de mídia, grupos
publicados/rascunhos, rollback e prévia desatualizada. Um importador sintético
restrito confirmou inclusão em **Caulim-Serpentina**, sobrescrita no mesmo PID,
vínculo idempotente e preservação da comunidade após a publicação nativa.
Todos os registros sintéticos foram retirados ao concluir os testes.
Evidências: `output/openalex-duplicates-admin-20261023/`.


## Classificação retroativa de registros existentes

O script `scripts/classify-existing-openalex.py` gera uma prévia independente
com comunidades atuais, sugestões, acréscimos e os termos/campos que sustentam
cada sugestão. O inventário usa PIDs ativos e agrupa versões/edições pelo parent;
registros retirados não são reintroduzidos. Nenhuma obra é importada novamente.

No runtime local Invenio, execute `preview --preview CAMINHO/preview.json`.
Os arquivos JSON, CSV e HTML são somente leitura do acervo. Para aplicar,
use `apply --preview CAMINHO/preview.json --sha256 HASH_EXATO
--database-backup CAMINHO/backup.dump`; o backup deve estar no formato
PostgreSQL custom. A opção `--rollback-only` ensaia a transação completa e
desfaz todas as associações, sem disparar a reindexação pós-commit.

A aplicação revalida vocabulário, permissões, comunidades e o snapshot completo
antes de gravar. Acrescenta somente destinos ausentes, pelo serviço nativo
`record_communities_service.bulk_add` nos publicados e pelo mesmo gerenciador
nativo do parent nos rascunhos. Mantém a comunidade padrão existente;
rascunhos permanecem sem publicação. Não edita metadados, arquivos ou versões.
O processo verifica essas invariantes antes do commit e registra a execução no
jornal OpenAlex. Atualiza de forma síncrona a busca das versões afetadas, além
da fila nativa, para não depender do agendamento de consumo em lote. Repetir
o mesmo plano concluído reutiliza o resultado, sem acrescentar vínculos.

As evidências da execução de 23/10/2026 ficam em
`output/openalex-existing-classification-20261023/`, incluindo prévia completa,
backup PostgreSQL, resultado e auditoria final. A classificação continua
sendo temática: resultados sem evidência não recebem associação automática.

## Revisão manual dos registros sem classificação

Na administração, abra **Povoamento → Registros sem classificação** e execute
**Verificar registros sem classificação**. A tarefa consulta registros e
rascunhos ativos e apresenta os casos sem destino confirmado pelo classificador.
Versões do mesmo parent aparecem uma vez. Registros retirados não retornam.
A lista permite buscar título ou identificador e diferencia publicados de
rascunhos. As comunidades exibidas na fila são as da data da verificação.

Abra **Revisar comunidades** para conferir autores, descrição, assuntos, termos
identificados e vínculos atuais. Os novos destinos começam desmarcados. Marque
somente as comunidades adequadas, acrescente uma justificativa opcional e use
**Revisar prévia dos acréscimos**. A prévia mostra separadamente os vínculos que
serão preservados e os que serão acrescentados, incluindo comunidades superiores
exigidas pelo vínculo nativo. Confirme a prévia para concluir a decisão.

Quando os vínculos atuais já forem suficientes, use **Revisar conclusão com
vínculos atuais** e confirme a prévia sem acréscimos. É necessário que o registro
já tenha ao menos uma comunidade. Essa opção registra uma decisão de curadoria;
não cria uma associação artificial para os casos sem destino adequado.

O processo permite apenas acrescentar comunidades ativas com permissão de
inclusão direta. Preserva todos os vínculos anteriores, a comunidade padrão
existente, metadados, arquivos, responsáveis, acesso e publicação. Não recria
registros ou rascunhos. Rascunhos continuam sem publicação. A operação usa uma
transação com bloqueio e valida novamente os dados, versões, destinos e
permissões. Uma mudança após a verificação exige nova prévia. Repetições do
mesmo envio reutilizam a tarefa existente.

Decisões concluídas aparecem no histórico com responsável, data, justificativa,
prévia e snapshots anteriores, disponíveis no relatório JSON administrativo.
Saem das próximas filas enquanto os termos revisados e os vínculos confirmados
permanecerem válidos. Mudanças em título/descrição/assuntos ou remoção de um
vínculo confirmado reabrem a revisão na próxima verificação. Na fila antiga,
a linha passa a apontar para o resultado concluído.

A busca é atualizada depois do commit. Se a indexação falhar, a tela informa
que a associação já foi gravada e oferece **Atualizar apenas a busca**, sem
repetir a associação. Falhas antes do commit não concluem a decisão e exigem
nova verificação. Os formulários são administrativos, com CSRF e respostas
privadas sem cache. A interface está disponível em português e inglês.

Validação desta extensão: 54 testes unitários e integração nativa com dois
registros sintéticos restritos, publicado e rascunho, incluindo rollback,
prévia desatualizada, idempotência, manutenção do padrão e dos vínculos,
conclusão sem acréscimos, saída da fila e controles HTTP. Os registros sintéticos
são retirados ao concluir os testes. Evidências em
`output/openalex-manual-review-20261023/`.


## Busca livre e combinada no OpenAlex

Em **Nova extração**, há três formas de coleta:

- **Vocabulário:** selecione um argilomineral e deixe o termo livre vazio. Mantém a seleção textual original do V59.
- **Busca livre:** selecione **Sem vocabulário** e informe um termo ou expressão, como `DRX`.
- **Combinada:** selecione um argilomineral e preencha o termo livre. A consulta exige os dois lados com `AND`, por exemplo `(DRX) AND ("kaolinite")`.

Para ampliar a sigla em português e inglês, pode usar `(DRX OR XRD OR "X-ray diffraction")` no campo livre. A expressão livre aceita a sintaxe de busca do OpenAlex, tem limite de 500 caracteres e não altera o vocabulário. Consulte a [sintaxe oficial](https://help.openalex.org/api/searching/).

Com termo livre, a escolha de um argilomineral usa seu identificador exato e exige deslocamento 0. A escolha **Todos** combina a expressão com cada termo, respeitando máximo e deslocamento no vocabulário. Sem vocabulário, máximo e deslocamento não se aplicam. **Resultados por termo** limita cada consulta. Para testar, mantenha **1, 1 e 0**.

A extensão usa o Python, transporte autenticado, normalizador, classificador, deduplicador e conversor bibliográfico da instalação V59 verificada. O V59 original e suas credenciais não são alterados. O agente Mac encaminha buscas livres/combinadas ao novo processo isolado; coletas somente por vocabulário mantêm o executável original.

Os resultados sem correspondência temática são preservados e ficam disponíveis para revisão/importação e classificação manual. O termo de busca não comprova associação mineralógica. Não são fabricados campos de amostra ou campanha. O lote contém `busca.json` com expressão e parâmetros, dados brutos, bibliografia e manifesto compatível; a preparação registra a consulta e seu hash na proveniência. A importação continua exigindo revisão e confirmação. Busca válida sem resultados termina com uma mensagem própria e não oferece preparar um lote vazio; erros HTTP são falhas, sem serem apresentados como zero resultados.

Validação: 67 testes unitários OpenAlex (13 de busca), integração offline do exportador/conversor V59 incluindo obras sem classificação e buscas reais limitadas a uma publicação, sem importar registros. Evidências em `output/openalex-search-20261024/`.


## DOI externo quando o registro local de DOI está desativado

O importador verifica os provedores efetivamente disponíveis no serviço nativo.
Se o provedor `external` de DOI estiver desativado, conserva o DOI de origem em
`metadata.identifiers` com esquema `doi`, preservando também o identificador
OpenAlex. A mesma verificação de identidade e os mesmos bloqueios contra
registros duplicados continuam ativos. Não habilita provedores ou solicita
registro de DOI. A revisão original permanece íntegra na proveniência e o
resultado indica `doi_storage: metadata_identifier` quando essa adaptação ocorre.
PIDs geridos localmente não são convertidos nem removidos.

Para repetir pela interface: abra **Importação OpenAlex → Lotes disponíveis →
Preparar revisão** no lote desejado, confira publicação/comunidades e confirme
**Importar, atualizar e classificar**. Se já existir DOI/OpenAlex correspondente,
a nova revisão aponta a atualização do mesmo registro, preservando arquivos,
acesso e vínculos anteriores. Reenviar a mesma seleção da mesma revisão retorna
a tarefa já existente. Uma coleta nova pode ser feita em **Nova extração**.

Validação complementar: 70 testes unitários OpenAlex, incluindo três de
compatibilidade do DOI externo, além da importação autorizada de
`10.1180/0009855023720042` como rascunho nas três comunidades revisadas.

## Publicação automática dos rascunhos importados — 24/10/2026

A publicação em lote complementa a etapa 4 de **Operação**: depois da
importação e da curadoria, é possível publicar pelo depósito nativo ou por
**Publicar rascunhos em lote**, na página de importação. O endereço direto é
`/administration/openalex/publication/`. A revisão ou tarefa de importação
também oferece **Publicar os rascunhos importados → Revisar publicação em lote**.

1. Selecione a **Revisão ou importação de origem**. Somente resultados
   efetivamente criados ou atualizados por importações dessa origem entram na
   verificação. Obras apenas presentes no lote, mas nunca importadas, ficam
   fora. Uma revisão pode reunir as importações concluídas associadas a ela.
2. Escolha **Registros por lote**: **100**, recomendado e padrão, **200** ou
   **500**. Esse número divide a execução automática; não limita o total de
   aptos nem exige nova confirmação a cada bloco.
3. Use **Revisar publicação em lote**. A prévia consulta o estado nativo,
   valida a publicação, confere DOI/OpenAlex, arquivos, visibilidade e
   comunidades, sem publicar ou alterar os registros. Aguarde a conclusão da
   verificação. Ela separa **aptos**, **já publicados** e **bloqueados**, com o
   motivo de cada impedimento.
4. Confira título, PID, comunidades e acesso. A prévia também diferencia
   rascunhos novos de edições pendentes de registros publicados. A
   configuração local atual permite publicar sem comunidade: esses aptos
   ficam sinalizados e podem ser classificados depois. Se a configuração
   nativa passar a exigir comunidade, a validação bloqueará esses casos.
5. Marque **Conferi a prévia. Publicar todos os aptos com a visibilidade atual**
   e confirme **Publicar todos os aptos**. A confirmação inicia todos os
   aptos da prévia, inclusive os que estão em outras páginas ou fora do filtro
   de exibição. Os filtros e a paginação servem para conferir os resultados;
   não selecionam um subconjunto para publicar.
6. Acompanhe a tarefa: a página atualiza automaticamente durante a execução
   e mostra publicados, novos, alterações publicadas no mesmo registro, já
   publicados, bloqueados e progresso processado. Há busca por título ou
   identificador, filtro de situação e até 20 registros por página. Os links
   levam ao depósito dos pendentes e ao registro nativo dos publicados.
7. Abra **Publicações e histórico** para retornar às prévias e execuções.
   Uma prévia já confirmada oferece **Acompanhar publicação** na tarefa
   existente. Baixe o CSV, o relatório JSON e os backups de cada lote.

### Preservação e bloqueios

A execução usa `current_rdm_records_service.publish()` no PID revisado.
Publica tanto rascunhos novos quanto edições importadas de registros
existentes, preservando PID e versão. Não abre outra versão para publicar a
edição. Confere a preservação de metadados bibliográficos e científicos,
arquivos e mídia, propriedade, acesso/embargo, comunidades e identificadores.
Mantém a visibilidade atual; a ação não converte todos os registros em acesso
público. PDFs continuam fora da coleta/importação OpenAlex, mas arquivos já
existentes nos registros atualizados são preservados e incluídos no backup
quando o registro está apto para execução.

Pedidos de revisão pendentes, falta de permissão, falha de validação nativa,
identidade divergente/duplicada, registro retirado ou mudança desde a prévia
impedem a publicação do item. Antes de cada escrita, a execução confere
novamente rascunho, publicação anterior, revisão do parent, arquivos e
vínculos. Uma alteração exige nova prévia; o plano confirmado não é
atualizado silenciosamente. Uma nova prévia reconhece os mesmos PIDs já
publicados e não os publica outra vez.

Há lock da tarefa, bloqueio das linhas nativas do parent/rascunho/publicação
e lock transacional compartilhado com as importações OpenAlex. A publicação
e seu checkpoint são confirmados na mesma transação **por registro**. Cada
lote é uma unidade de agendamento e backup, não uma transação única de 100,
200 ou 500 registros. Um item bloqueado fica no relatório; os seguintes
podem continuar. A situação **Concluída** deve ser lida junto dos contadores
e motivos: ela indica processamento encerrado e pode incluir bloqueados.

### Retomada e backups de publicação

O worker agenda automaticamente o próximo bloco, e a recuperação existente
reenfileira tarefas pendentes. Após falha de infraestrutura, o administrador
responsável pela tarefa pode usar **Retomar do último registro concluído**.
A retomada conserva o plano, os resultados e o checkpoint, sem reaplicar
publicações confirmadas. Reenviar a confirmação da mesma prévia retorna à
mesma execução. Para itens bloqueados por dados alterados ou validação,
corrija o impedimento e prepare outra prévia da origem.

Uma indisponibilidade do OpenSearch pode ocorrer depois de a publicação e o
checkpoint já terem sido confirmados no PostgreSQL, durante o hook de
indexação. No início de cada bloco ou retomada, `repair_checkpoint_index`
reindexa o último item confirmado como `published`, lendo a publicação
nativa atual. Remove somente a cópia obsoleta do índice de rascunhos quando
o rascunho nativo foi excluído logicamente; qualquer rascunho ativo é
preservado. Essa recuperação não chama `publish()`, não altera contadores,
metadados ou PIDs e não atua sobre um último item bloqueado ou sem
checkpoint confirmado.

Antes da primeira publicação de cada bloco, o módulo cria e valida um ZIP
privado e registra seu SHA-256 na tarefa. O manifesto contém plano/hash,
itens e snapshots anteriores de rascunhos e parents; quando há uma edição,
inclui também a publicação anterior. Os binários de arquivos e mídia dos
estados preservados entram no ZIP com seus nomes originais registrados no
manifesto. São conferidos tamanho, checksum nativo, integridade do ZIP e
hash final. Falha, ausência ou alteração de um backup já registrado
interrompe a execução, preservando os checkpoints concluídos.

No Mac, os arquivos ficam em
`argiloteca-rdm14-hml/data/openalex-admin-queue/publication-backups/<id-da-tarefa>/`,
com diretório privado e ZIPs de permissão `0600`. O download administrativo
valida o SHA-256 registrado e recusa arquivo ausente, divergente ou link
simbólico. Esses backups são próprios da publicação; os de consolidação de
duplicados continuam em seu diretório anterior. O fluxo não oferece um botão
de restauração automática. Os relatórios CSV/JSON registram situações e
mensagens; o JSON também contém parâmetros, prévia, resultados e manifesto
dos backups.

### Validação da extensão de publicação

Foram aprovados 12 testes unitários específicos de publicação e verificações
nativas de PT/EN, filtros/paginação, acesso anônimo negado, CSRF, confirmação
imutável, idempotência, backup e links para o registro. Uma prévia repetida
reconheceu os dois registros já publicados, sem aptos ou bloqueados. Os
resultados anteriores de 70 testes pertencem ao conjunto de importação e
busca documentado acima; não representam o total do teste específico novo.
Dois dos testes específicos cobrem a recuperação da indexação após commit,
a preservação de rascunho ativo e a ausência de ação para item bloqueado ou
sem confirmação.

As evidências estão em `output/openalex-publish-20261024/`, incluindo
`unit-publication.log`, `validate_routes.log`, `routes-final.log`,
`progress-desktop-fixed.png`, `mobile-confirmation-clear.png` e
`finish-review.md`. O parecer visual registrou `ship` após resolver a
sobreposição do assistente no celular, a 320 px CSS. A mesma instância do
launcher participa do fluxo de `argilo-admin-content` nas páginas OpenAlex;
as outras rotas preservam a posição existente.

A execução real de referência usa a origem
`34c40a12acf84dc8b0f0118172379a4b`, a prévia
`3c89eb3de3f24694a68b0ac52acb1bb8` e a publicação
`cfb11f3d46af4a848ebb013d839fead8`. A tarefa terminou como **Concluída**:
**5.645 de 5.645 publicados**, sendo **5.141 primeiras publicações** e
**504 edições publicadas no mesmo PID**, sem bloqueados ou itens marcados
como já publicados nesta execução. A importação anterior havia criado 5.140
rascunhos e atualizado 505 existentes; um desses 505 ainda era um rascunho
sem publicação. Isso explica a primeira publicação adicional, sem criar
um registro duplicado. Os 118 itens originais não aptos permaneceram fora da
execução. Os 71 publicados sem comunidade continuam sinalizados e permitidos
pela configuração atual.

A auditoria final em `verification.log` confirmou correspondência única de
identidade para os 5.645 itens, fechamento dos 5.645 rascunhos de origem,
preservação de outros 55 rascunhos e de 7.412 parents com seus vínculos e
propriedade. Conferiu 140 arquivos, totalizando 172.573.768 bytes, com
checksums preservados, e 57 ZIPs de backup íntegros por CRC/SHA-256 que cobrem
os 5.645 itens. O hash do SQLite de origem permaneceu inalterado.
`search-verification.log` confirmou os 5.645 documentos nativos no alias de
busca com múltiplos índices, com o mesmo UUID/PID e um documento por ID.

O backup PostgreSQL anterior, de 118.703.378 bytes, foi validado por leitura
integral com `pg_restore`, sem restauração. Os 12 testes unitários passaram;
as rotas de `routes-final.log` também passaram após a conclusão. A captura Firefox
`publication-completed.png` registra o resultado final. Essas evidências
complementam os testes e a revisão visual descritos acima.

Durante essa carga, após 5.301 publicações confirmadas no PostgreSQL, houve
uma queda temporária de conexão do OpenSearch. O serviço reiniciou e voltou
ao estado saudável; não houve falta de memória no worker. Checkpoint e
backups foram preservados, e a retomada pelo botão avançou além de 5.355
publicações sem republicar os itens confirmados. Essas contagens descrevem
o incidente e sua recuperação; o resultado final é o auditado acima.

## Estatísticas OpenAlex e autores com ORCID — 24/10/2026

As entradas **Povoamento → Estatísticas OpenAlex** e **Autores e ORCID**
usam a mesma administração protegida. Acesso direto às estatísticas:
<https://127.0.0.1:5101/administration/openalex/statistics/?ln=pt>.
Lista de autores:
<https://127.0.0.1:5101/administration/openalex/authors/?ln=pt>.

### Consultar as estatísticas

1. Use **Atualizar estatísticas e autores** para preparar um retrato em
   segundo plano. Acompanhe a tarefa pelo link exibido. Essa leitura não
   altera registros nativos; o painel informa a data de preparação em UTC.
2. Filtre o intervalo de anos, tipo de fonte e assunto ou palavra-chave.
   Confira a **Cobertura do recorte** antes de interpretar os rankings.
3. Explore **Publicações por ano**; **Série completa** inclui toda a extensão
   temporal. Os rankings têm **Mostrar até 15** e **Ver dados e links** para
   valores exatos. **Exportar rankings CSV** usa os mesmos filtros. Os
   controles dos gráficos entregues em 26/10 estão detalhados abaixo.

As contagens usam obras publicadas distintas por DOI/OpenAlex; identidades
repetidas excluídas são sinalizadas. Um trabalho pode pertencer a vários
assuntos, instituições ou países: não some esses totais. Autores OpenAlex
são perfis bibliográficos sujeitos a revisão de identidade. Citações
refletem a data de coleta de cada origem e não são atualizadas em tempo
real, nem equivalem ao fator de impacto JIF. O lote V59 preserva Concepts
e palavras-chave, mas não Topics ou FWCI. Métricas Scopus/JCR não integram
este painel. Os lotes e hashes de origem podem ser consultados em
**Fontes e limites**.

O retrato é um SQLite privado em disco, com leitura nativa por blocos de
100 e entradas RAW limitadas a 16 MiB. Ele auxilia estatística e descoberta;
não substitui os registros nativos. A revisão de autoria inclui ocorrências
pessoais de publicações e rascunhos, enquanto os rankings de produção usam
somente publicações OpenAlex.

### Buscar e revisar ORCID de autores existentes

1. Em **Autores e ORCID**, pesquise o nome e, se útil, filtre ocorrências
   sem ORCID ou com sugestões coletadas. Cada página mostra até 20 grupos
   de nomes. Abra **Revisar e buscar ORCID**.
2. Confira as ocorrências, obras e posições do autor. Um grupo com o mesmo
   nome serve apenas para localizar ocorrências; não comprova que todas
   pertencem à mesma pessoa. Não há cadastro paralelo de pessoas.
3. Compare as sugestões já preservadas no OpenAlex. Para outra consulta,
   preencha nome ou sobrenome e, opcionalmente, instituição e DOI de uma
   obra, e use **Buscar no ORCID**. Os termos preenchidos são enviados à
   API pública ORCID. Até 20 candidatos são exibidos; refine a busca quando
   necessário. **Abrir busca no site ORCID** oferece a consulta no site.
4. Se já conhece o identificador, abra **Já tenho o ORCID: consultar perfil
   público**, informe o ORCID e use **Consultar perfil e obras**. Confira
   o perfil, nome, instituições e obras/DOIs públicos disponíveis. Resultado
   público ou sugestão OpenAlex é evidência candidata, não autenticação
   feita pelo pesquisador.
5. Escolha o ORCID após a conferência e marque explicitamente as ocorrências
   existentes da página que pertencem àquela pessoa. Nenhuma é selecionada
   automaticamente. Use **Preparar prévia dos vínculos**; a API aceita de
   1 a 100 ocorrências distintas por prévia. A interface seleciona as
   ocorrências da página atual.
6. Na prévia, confira registro, autor, posição, identificador e estado final
   de cada ocorrência. Se útil, abra **Registrar evidências da revisão
   (opcional)** e anote as fontes consultadas e o motivo da correspondência
   (até 2.000 caracteres). Marque a declaração obrigatória **Conferi as obras
   e a identidade da pessoa. Aprovo somente os vínculos desta prévia** e use
   **Salvar ORCID revisado** (**Save reviewed ORCID** em inglês).
7. Confira **ORCID revisado salvo**, os mesmos registros, horário UTC e as
   evidências registradas. Use **Baixar backup da vinculação** quando disponível.
   Atualize o retrato para refletir os novos identificadores na lista de
   autores. Caso a escrita tenha terminado e a busca esteja pendente, use
   **Atualizar índice sem reaplicar vínculos**.

O destino é o modelo nativo InvenioRDM, na posição existente de
`metadata.creators[].person_or_org.identifiers[]`, acrescentando
`{"scheme":"orcid","identifier":"0000-0000-0000-0000"}` com o
identificador validado, incluindo dígito verificador. A confirmação e a nota
opcional são auditadas com administrador e horário UTC nos parâmetros da
tarefa de aplicação e no manifesto do backup. O exemplo mostra
somente o formato; não é um identificador a aplicar. Não cria, funde ou
reordena autores e não propaga vínculos pelo nome. Preserva outros
identificadores, nomes, afiliações, papéis, metadados, arquivos e mídia,
acesso, propriedade e comunidades.

Para publicados, o serviço nativo faz `edit`, `update_draft` e `publish`
no mesmo PID/UUID. Para rascunhos, atualiza o rascunho e mantém seu estado
não publicado. Publicação com rascunho de edição pendente exige revisão
desse rascunho e fica bloqueada neste fluxo. Outro ORCID já presente não
é substituído; o mesmo ORCID já presente não gera alteração. O mesmo ORCID
em duas posições do mesmo registro é bloqueado. Revisões, fingerprints e
bloqueios nativos impedem aplicar uma prévia cujo registro, autoria ou
vínculos tenham mudado; prepare nova prévia nesses casos. Reenviar a
confirmação não enfileira outra aplicação.

### Backup, falhas e consulta pública

Antes da escrita, um ZIP privado preserva a prévia, os metadados completos
anteriores e os binários dos arquivos/mídia, com checksum, tamanho, CRC e
SHA-256 verificados. O destino é
`ARGILOTECA_OPENALEX_QUEUE/orcid-backups/<job-id>.zip`, com download
administrativo protegido. Falha de integridade ou mudança de estado impede
a aplicação. O fluxo não oferece restauração automática. Uma falha de
indexação após o commit é recuperada apenas no índice, sem republicar ou
reaplicar o ORCID.

A consulta usa o servidor fixo `https://pub.orcid.org/v3.0/`, sem seguir
redirecionamentos, com limite de resposta de 8 MiB e tratamento de limite
temporário/indisponibilidade. Se a API exigir autorização, configure o token
público opcional `ARGILOTECA_ORCID_READ_PUBLIC_TOKEN` no ambiente local ou
use a busca no site oficial. Não coloque credenciais nos formulários. Uma
consulta com falha preserva a prévia local. Esse mecanismo não implementa
OAuth do pesquisador nem comprova sua autorização pessoal para o vínculo.

### Evidência e estado de referência

Em `output/openalex-statistics-orcid-20261024/`, `unit.log` registra 18
testes aprovados. `routes-final.log` cobre PT/EN, exportação de 113 linhas
CSV, 403 anônimo, 400 CSRF, rejeição de seleção duplicada e autoria alterada,
e POST de aplicação repetido sem nova execução. Essas verificações não
escreveram vínculos nativos.

`native-apply-rollback.log` exercitou `edit/update_draft/publish` no registro
`2wj4w-c9b76`, somente com flush SQL e hooks de commit desabilitados, seguido
de rollback verificado: autoria, IDs, arquivos, comunidades e contagens
nativas ficaram preservados. `native-file-backup.log` validou um backup de
2.090.343 bytes com um arquivo binário, checksum e CRC, sem escrita nativa.

`statistics-streaming.log` registra 5.645 obras em 8,61 s, pico de 298,9 MiB
de RSS (+22,7 MiB), SQLite de 92.876.800 bytes e zero escritas nativas. O
retrato `2960155f30d5448cb23a01baf9f940e5` contém 5.645 obras publicadas,
19.415 ocorrências pessoais nativas incluindo rascunhos, 12.555 grupos de
nomes e 9.481 ocorrências com candidatos coletados. Esses grupos não são
uma contagem de pessoas identificadas.

A consulta real `62eb07bc0f434a0886bbb94cf99fced7` por James Harsh retornou
`0000-0002-0177-3342`. A prévia administrativa
`f4b16550d8984aa2932a06b80bd0eea7` relaciona o candidato à ocorrência
existente de James B. Harsh na posição 1 de `2wj4w-c9b76` e estava em
**revisão**, sem aplicação, no fechamento de 24/10. `source-integrity.json`
registra zero tarefas reais de aplicação naquele momento e hash da revisão
de importação original inalterado. A aplicação confirmada em 26/10 está
registrada na seção seguinte. Prévia disponível em
<https://127.0.0.1:5101/administration/openalex/authors/jobs/f4b16550d8984aa2932a06b80bd0eea7?ln=pt>.

As capturas de desktop/celular e estados PT/EN estão em
`.impeccable/review/openalex-statistics-orcid/`. O parecer final fornecido
pelo reviewer registra `ship` das correções PT/EN revistas, com os itens
pontuados resolvidos; não representa uma nova revisão integral. A extensão
preserva o sistema visual administrativo e não cria DESIGN.md, sidecar ou
raster. A documentação usa as evidências existentes, sem repetir consultas,
testes, detector ou sessão de navegador.

### ORCID revisado salvo — 26/10/2026

A prévia pendente `f4b16550d8984aa2932a06b80bd0eea7` foi conferida e salva
pela interface. A tarefa `109ec2a834044dd2a40813155cd49282` concluiu a
atualização de **uma ocorrência**, James B. Harsh na posição 1 de
**Allophane and Imogolite**, PID `2wj4w-c9b76`, DOI
`10.2136/sssabookser7.c9`, com ORCID `0000-0002-0177-3342`.
A fonte editorial identifica James Harsh e Washington State University;
o perfil institucional [EMSL/PNNL](https://www.emsl.pnnl.gov/people/james-harsh)
explicita o mesmo ORCID. Essas fontes sustentaram a revisão administrativa
registrada; não houve OAuth do pesquisador.

O salvamento reutiliza o campo nativo existente do autor selecionado. Não
cria pessoas, não funde autores e não aplica sugestões em massa. A auditoria
confirmou o mesmo PID/UUID e a preservação exata do restante dos metadados,
arquivos, comunidades e autores, acrescentando somente o ORCID na posição
revista. Permaneceram 7.402 registros, 7.412 parents, 140 arquivos,
172.573.768 bytes e 27.894 posições de criadores. O identificador foi
confirmado no índice nativo ativo; o reenvio real do POST retornou à mesma
tarefa concluída sem criar outra aplicação.

O **backup da vinculação** disponível na tarefa tem 5.423 bytes e SHA-256
`b58d27a466bf82f514052d71701a3f2bcba289a625cd25fcb6f03febd66e68c5`.
Foram verificados CRC, hash, permissão `0600`, download administrativo
protegido e confirmação/administrador/horário/evidência no manifesto.
Depois do salvamento, **Atualizar estatísticas e autores** concluiu o novo
retrato `fda9c653f9cc4e95a025ed4db0638b33` pela interface. A lista de James
B. Harsh mostra cinco registros, um com ORCID vinculado e quatro sugestões
ainda por revisar; `author-list-updated.png` registra essa conferência.

As evidências estão em `output/orcid-reviewed-save-20261026/`:
`verified-save.json` registra os resultados nativos aprovados; `unit.log`
registra 18 testes aprovados; `routes-save-test.log` registra PT/EN,
autorização administrativa, CSRF, confirmação/auditoria, rejeição de
seleção duplicada e prévia desatualizada, sem escrita nativa nesse teste.
Os testes de integração também cobrem o limite de 2.000 caracteres da nota.
As quatro capturas desktop/celular mostram prévia e recibo. O detector
registrou `[]`, com aviso de resolução de CSS no Jinja; `finish-review.md`
registra **ship**, sem correção material, e o suplemento da auditoria nativa
concluída.

Para próximas revisões, siga **Autores e ORCID → revisar candidato e
ocorrências exatas → preparar prévia → conferir identidade e marcar a
declaração → Salvar ORCID revisado → conferir recibo e backup**. Cada
salvamento depende dessa revisão explícita; o nome agrupado não autoriza
propagação nem a aplicação de candidatos não revisados.

## Gráficos das estatísticas OpenAlex — 26/10/2026

Na mesma página **Estatísticas OpenAlex**, a cobertura do recorte antecede
nove gráficos: publicações por ano, tipos de fonte, periódicos e fontes,
autores, assuntos (Concepts), palavras-chave, instituições, países e obras
mais citadas. A referência de organização analítica foi o Radar Rede Clima
indicado pelo usuário; navegação, marca e controles continuam na
administração InvenioRDM existente.

1. Preencha anos, tipo de fonte e assunto/palavra-chave e use **Filtrar**.
   Confira os quatro indicadores de cobertura antes dos gráficos. **Limpar
   filtros** conserva o retrato selecionado.
2. A série anual abre nos últimos 30 anos do recorte com ano conhecido;
   use **Série completa** e **Últimos 30 anos** para alternar. O eixo usa
   distâncias numéricas entre anos e representa como zero os anos
   intermediários sem obras. Obras sem ano ficam na tabela e na indicação
   ao lado do intervalo. Selecione um ano no gráfico ou na tabela para
   restringir ambos os limites, mantendo fonte e assunto.
3. Os rankings abrem com seis posições, ou cinco nas obras mais citadas.
   **Mostrar até 15** amplia o gráfico; **Mostrar menos** reduz. Tipos de
   fonte exibem também **Não informado**, sem ocultar a falta de metadados.
   Selecione uma barra de Concepts ou palavras-chave, ou seu link na
   tabela, para preencher o filtro de assunto, mantendo anos e fonte.
4. Abra **Ver dados e links** para nomes completos, valores exatos e links
   disponíveis. A tabela anual contém a série inteira; os demais rankings
   têm até 15 resultados. Nas citações, o link abre o registro nativo; nos
   autores, abre o perfil OpenAlex. Sem JavaScript, as tabelas já ficam
   abertas; falha do gráfico reabre a tabela correspondente.
5. Use **Exportar rankings CSV** para o mesmo retrato e filtros. A janela
   visual de seis/cinco posições e a alternância temporal não limitam o
   CSV. No celular os painéis passam a uma coluna e os valores completos
   continuam nas tabelas.

**Atualizar estatísticas e autores** mantém a preparação em segundo plano
do retrato privado. Consultar gráficos, aplicar filtros e exportar CSV são
leituras; a preparação do retrato não altera registros científicos nem
aplica identificadores pessoais. Uma vinculação ORCID continua dependendo
da revisão explícita descrita acima.

### Retrato, limites e implementação local

O retrato de referência mais recente, preparado em 26/10 às 14:08 UTC, é
`3f587c077dfd451d879ba7ab482a41fb`: **5.645 publicações distintas**,
**1.165 IDs de fontes**, **10.795 perfis bibliográficos OpenAlex** e
**341.488 citações coletadas**. Há cinco obras sem ano e 220 sem fonte
informada; 5.425 das 5.645 obras possuem fonte. Esses números descrevem o
retrato e mudam conforme os filtros ou uma nova preparação. Perfis OpenAlex
não são pessoas identificadas por ORCID. Assuntos, instituições e países
podem se sobrepor; seus totais não devem ser somados. Permanecem os lotes e
hashes em **Fontes e limites**, as citações na data da coleta e a ausência
de JIF, Scopus/JCR, FWCI e Topics não coletados no lote V59.

React/Recharts são servidos localmente pelo runtime fixado de Data 1.0.11
em `argiloteca/static/vendor/data-charts/`, sem CDN, editor Data completo
ou Site externo. O runtime tem 1.968.401 bytes; `provenance.json` registra
hashes e `THIRD_PARTY_NOTICES.txt` acompanha as licenças. A reprodução,
a partir da raiz do repositório, usa
`node scripts/vendor_openalex_chart_runtime.mjs /caminho/absoluto/do/plugin-data`;
o script verifica o artefato instalado e não baixa dependências. Não há
novo endpoint de escrita. Autorização administrativa, CSRF, filtros GET,
CSV e ações nativas permanecem no fluxo existente.

O filtro de assunto usa uma subconsulta de IDs correspondentes em vez de
repetir uma busca correlacionada em cada linha de autoria ou tag. Preserva
a semântica do recorte e as contagens distintas. Na medição local fornecida,
três leituras combinadas passaram de 25,957 s para 8,131 s; a duração depende
do recorte e do ambiente.

### Evidência dos gráficos

Em `output/openalex-visual-statistics-20261026/`, `unit.log` registra
**21 testes aprovados** e `verified-charts.json` reconcilia SQL e CSV em
quatro casos: 5.645 obras sem filtros, 557 periódicos desde 2020,
682 obras com Kaolinite e zero obras em um recorte vazio. Também registra
PT/EN, primeiro retrato ausente, 403 anônimo, 400 CSRF, conciliação de
anos/tipos de fonte e registros nativos inalterados. Não houve escrita
de registros ou identificadores pessoais nessa validação.

`finish-review.md` registra **ship**, sem correções materiais. As seis
capturas existentes em `.impeccable/review/openalex-visual-statistics/`
são `desktop.png`, `desktop-charts.png`, `desktop-subjects.png`,
`mobile.png`, `mobile-charts.png` e `mobile-rankings.png`: viewports nativos,
não capturas de página inteira. A revisão registra a prioridade dos
controles empilhados no primeiro viewport móvel, com cobertura e gráficos
logo abaixo. O detector já executado sinalizou Lato, preservado pelo
compromisso de marca; seu aviso de resolução de CSS em Jinja foi coberto
pela leitura direta do CSS. Não são motivos para alterar a tipografia
global. Esta extensão mantém o sistema existente e não cria DESIGN.md,
sidecar, raster ou novos tokens globais.

## Topics, hierarquia, FWCI e percentis — 26/10/2026

O painel **Estatísticas OpenAlex** oferece **Atualizar Topics e métricas**.
Esse fluxo acrescenta uma camada analítica versionada ao retrato existente;
preserva registros nativos, autores, ORCID, arquivos, comunidades e os lotes
de origem. A ausência de Topics/FWCI no lote V59 continua documentada: os
novos valores provêm de coleta complementar identificada, sem preencher
ausências por inferência. Concepts e palavras-chave continuam nas seções
anteriores. A interface mantém administração nativa, Catamaran/Lato,
marrom/laranja, SVG e PT/EN.

### Coletar e revisar

1. Abra **Atualizar Topics e métricas** em
   `/administration/openalex/statistics/`. Em **Escopo da prévia**, escolha
   **Todas as publicações do retrato** ou **Exemplo real: primeiras 100**.
   O escopo contém obras publicadas distintas com OpenAlex no retrato
   congelado selecionado; não inclui automaticamente publicações posteriores
   ou todos os rascunhos/importados. Prepare outro retrato para atualizar esse
   universo.
2. A coleta percorre blocos de 100 em segundo plano, com checkpoint por
   bloco. A página ocupada atualiza a cada 10 segundos e permite sair e
   voltar. Limites/indisponibilidade da API mostram espera agendada; 429,
   5xx e falhas de rede usam `Retry-After` e backoff limitado. Após falha,
   **Retomar coleta** continua do checkpoint sem consultar novamente os itens
   concluídos. A recuperação da fila considera tarefas em execução paradas
   por 10 minutos.
3. Na prévia selada, use filtro de situação e páginas de 20 itens. Confira
   publicação nativa, DOI/ID OpenAlex, motivo da correspondência, tópico
   principal/hierarquia, FWCI, percentil, atualização da fonte e coleta UTC.
   **Comparar valores anteriores e propostos** expõe os campos completos,
   incluindo Topics/pontuações, citações e histórico anual. O formulário em
   revisão não atualiza automaticamente.
4. Correspondências exatas usam ID OpenAlex e DOI conferido quando
   disponível, ou DOI canônico normalizado exato. Conflitos não são
   resolvidos por título. Em **Bloqueado: revisar**, confira a identidade na
   fonte; havendo candidatos, escolha um, registre justificativa de 10 a
   2.000 caracteres e digite `REVISADO`. **Salvar revisão em nova prévia**
   cria outro plano auditado e mantém o original. Sem candidato utilizável,
   revise os identificadores no registro nativo e prepare outra coleta.
5. **Ver gráficos desta prévia** abre uma simulação identificada, somente
   leitura, com `enrichment=preview:<id>`. A versão da prévia acompanha
   filtros e exportações; abrir esse endereço não ativa valores.

Esperas longas da API persistem o estado `waiting_api` e `retry_at`, exibindo
**Aguardando a API / Waiting for API** e mantendo o acompanhamento automático.
A execução retorna sem agendar Celery ETA. A tarefa de recuperação existente,
a cada 30 segundos, reenfileira apenas `waiting_api` cujo horário venceu;
assim, esperas longas por quota não acumulam tarefas agendadas na memória do
worker.

A credencial usa a montagem local V59 existente somente para leitura e é
enviada exclusivamente no cabeçalho Bearer para a API OpenAlex. Não aparece
em URL, parâmetros da tarefa, prévia, logs, CSV ou backup. Chave ausente ou
inválida exige corrigir a configuração local do extrator. A consulta usa
campos permitidos, timeout, sem redirecionamento e limite de resposta de
16 MiB. Quotas e disponibilidade externas podem alongar a coleta.

### Confirmar, conferir o recibo e recuperar

Marque **Selecionar esta publicação** nos aptos da página atual. A seleção
não persiste ao navegar para outra página. Para incluir todos os aptos de
todas as páginas, marque explicitamente **Aplicar todos os aptos desta
prévia**. Confira o alcance e digite `APLICAR` em **Aplicar complementos
revisados**. O plano selado e seu hash são conferidos novamente; o serviço
revalida fingerprints nativos sob bloqueios compartilhados antes da
ativação. Mudanças posteriores à prévia impedem aceitar silenciosamente
dados desatualizados.

Cada aplicação gera arquivo SQLite privado imutável em
`ARGILOTECA_OPENALEX_QUEUE/enrichment/`, com permissão `0600`; um ponteiro
SQL único indica a versão vigente. Os dados aprovados são sobrepostos apenas
na consulta analítica temporária; o retrato estatístico original permanece
preservado. Ativações e recuperações são serializadas. O recibo informa
alterações, valores já iguais, falhas, responsável, horário e método.

O método `argiloteca-openalex-enrichment/1.0; OpenAlex API; Topics October 2026`
é a identificação local do adaptador e da referência documental consultada,
não um identificador de release do dataset OpenAlex. O payload registra
`collected_at` e `updated_date`, mas a API não fixa neste fluxo um release de
snapshot do provedor. A [documentação Topics consultada na implementação](https://help.openalex.org/data/topics/)
registra mudança de classificador em outubro de 2026; `updated_date` sozinho
não permite identificar essa mudança com segurança. Preserve versão local,
datas e payload para comparar coletas; os lotes de origem continuam imutáveis.

Antes da ativação, um ZIP privado preserva a prévia selada, a versão
analítica anterior e o manifesto de auditoria. CRC e SHA-256 são verificados;
falha de integridade impede ativar. O checkpoint do backup persiste mesmo
em interrupção posterior. Use **Baixar backup verificado** no recibo e
confira o SHA-256 mostrado. O download exige administração.

Enquanto essa aplicação for a versão ativa, abra **Recuperar a versão
analítica anterior**, digite `RESTAURAR` e use **Restaurar versão anterior**.
A recuperação verifica o ZIP e restaura o ponteiro anterior; pode reconstruir
o SQLite anterior ausente a partir do backup. Na primeira aplicação,
recupera o retrato original sem complementos. Backup, auditoria e versão
substituída ficam preservados. Essa recuperação alcança a camada analítica,
pois o fluxo não escreve dados nativos.

Na instalação, `openalex.models.install_tables()` cria aditivamente
`argiloteca_openalex_analytic_head` e inicializa a linha única `id=1` sem
substituir estado existente. O script existente
`argiloteca-rdm14-hml/scripts/openalex-local` chama essa instalação.

### Ler cobertura, gráficos e CSV

Os novos filtros de tópico principal, subárea, área e domínio usam IDs
OpenAlex exatos, combinados com os filtros anteriores. Cobertura e gráficos
usam o mesmo retrato, versão analítica e recorte. Links e CSV fixam essa
versão para que uma ativação posterior não altere a população exportada.

A tabela de cobertura inclui explicitamente lista de Topics, tópico
principal, subárea, área e domínio, além das métricas, com disponíveis,
ausentes e denominadores do recorte. Uma lista `topics=[]` é fornecida mas
vazia; não é confundida com ausência/desconhecimento do campo.

- A hierarquia principal conta cada obra classificada uma vez por nível;
  ausência fica na cobertura. Agrupar por ID evita fundir rótulos iguais.
  Topics adicionais excluem o principal da própria obra, contam obras
  distintas por ID e podem se sobrepor; não some seus totais.
- FWCI usa o valor informado pela fonte e referência mundial em 1. A última
  faixa numérica reúne valores ≥10; o valor exato continua no CSV. Ausência
  não é zero e fica fora das faixas.
- O percentil normalizado vem como fração 0–1 e aparece em faixas
  percentuais. Participações top 1% e top 10% usam somente flags Booleanas
  conhecidas da fonte, com denominador próprio; esses grupos se sobrepõem.
  Não se deduzem flags a partir de valores ausentes.
- O histórico anual fornecido pela fonte contém os últimos 10 anos
  disponíveis e omite anos com zero. Citações e FWCI não são JIF; não há
  equivalência com Scopus, SciVal ou JCR. Topics são classificações
  automáticas. A ajuda aponta para a [metodologia OpenAlex](https://help.openalex.org/data/works/attributes/).
- **Ver dados e links** mantém nomes e valores exatos acessíveis, inclusive
  sem JavaScript. Rankings mostram no máximo 15 posições. **Exportar valores
  por publicação CSV** contém toda a população filtrada, com RID, DOI,
  OpenAlex, hierarquia, IDs/pontuações de Topics, Topics em JSON, FWCI,
  percentil/flags, citações/histórico, método, fonte e datas. A primeira linha
  identifica retrato e versão. **Exportar rankings CSV** continua disponível
  para os agregados.

O CSV por publicação conserva as colunas anteriores até `method` e acrescenta
`source_url`, `primary_topic_id`, `primary_topic_score` e `topics` (JSON).

### Rotas e validação fornecida

As rotas abaixo pertencem ao blueprint administrativo existente, sob
`/administration/openalex`. Os cinco POSTs exigem administração e CSRF.

| Método | Caminho | Uso |
| --- | --- | --- |
| GET | `/enrichment/` | Escopo, coletas, aplicações e recuperações |
| POST | `/enrichment/collect` | Enfileirar coleta |
| GET | `/enrichment/jobs/<id>` | Progresso, revisão e recibo |
| POST | `/enrichment/jobs/<id>/resume` | Retomar coleta falha |
| POST | `/enrichment/jobs/<id>/review` | Criar nova prévia com revisão de identidade |
| POST | `/enrichment/jobs/<id>/apply` | Confirmar seleção revisada |
| GET | `/enrichment/jobs/<id>/backup` | Baixar ZIP verificado |
| POST | `/enrichment/jobs/<id>/restore` | Recuperar versão anterior |
| GET | `/statistics/metrics.csv` | Valores por publicação no recorte fixado |

Em `output/openalex-enrichment-20261026/`, `unit.log` registra 15 testes
novos e `existing-tests.log` registra 22 existentes aprovados. Cobrem revisão
manual em novo plano e interrupção após checkpoint de backup. Aplicação
e restauração, incluindo arquivo anterior ausente, usam stores
temporários e ponteiros SQL simulados. Nenhuma aplicação analítica real foi
feita nesta entrega.

O teste de checkpoint/retentativa também verifica o estado `waiting_api` e
retorno sem tarefa adiada. Os resultados fornecidos permanecem em 15 testes
novos e 22 existentes aprovados. Essas correções de estado e cobertura não
mudam o layout dos formulários de revisão ou gráficos capturados.

`verified-interface.json` registra PT/EN, paginação, filtros inválidos,
403 anônimo e 400 sem CSRF nos cinco POSTs. SQL/CSV concordam em seis recortes:
5.645 obras sem filtro (88 FWCI), 557 periódicos desde 2020 (11 FWCI),
95 obras no domínio 3 (84 FWCI), 35 na área 25 (32 FWCI), 29 no tópico
T11852 (26 FWCI) e zero com ano inicial 9999. A simulação abrange o retrato
completo; obras fora da prévia aparecem com complementos ausentes.

A prévia real `193d8f8c39324d4ea7ac74e57c43c51d`, sobre o retrato
`3f587c077dfd451d879ba7ab482a41fb`, tem 100 aptos, 88 FWCI e zero
bloqueados/sem correspondência/erros. Está disponível para revisão posterior
do administrador; o ponteiro analítico ativo permanece NULL. Hashes e
contagens nativas e de arquivos permaneceram preservados.
`full-scope-profile.json` registra apenas inicialização isolada das 5.645
obras: 4,388 s e pico adicional de 2,62 MiB de memória Python rastreada,
sem chamadas de rede. Não mede coleta completa pela API nem RSS do processo.

As capturas em `.impeccable/review/openalex-enrichment/` incluem prévia,
simulação e métricas desktop, e prévia, confirmação e métricas móveis.
Desktop: 1712×1008 px CSS, imagem 3424×2016. Celular: Firefox em
390×844 px CSS/DPR 2, imagem nativa 780×1688, sem entorno do navegador.
O review integral apontou um recorte de rótulos desktop; o último
`finish-review.md` registra `ship` da correção pontuada, sem nova revisão
integral. O detector retornou `[]` com avisos de resolução de CSS Jinja,
cobertos por leitura direta dos estilos. Esta documentação reutiliza essas
evidências; não repete navegador, detector ou testes nem altera o sistema
visual global.

## Atualizar dados do Acervo pela interface — 26/10/2026

O botão **Atualizar dados do Acervo** aparece para administradores na busca
`/search` e nas páginas `/records/<rid>`. O mesmo destino está no menu
**Povoamento** e nas estatísticas OpenAlex. Os links abrem
`/administration/openalex/enrichment/`, que mostra a cobertura aceita, o
recibo e backup da versão ativa, a ação de atualização e o histórico.

1. Abra **Atualizar dados do Acervo** e confira o alcance: Topics,
   hierarquia, citações, FWCI e percentis OpenAlex.
2. Acione o botão principal na tela administrativa. Ele atualiza o
   inventário das publicações existentes e prepara uma prévia completa em
   lotes de 100. Acompanhe a tarefa; indisponibilidade ou quota da API pode
   adiar a conclusão, com os estados e a retomada já descritos acima.
3. Revise a prévia e os impedimentos. Selecione os aptos da página ou marque
   explicitamente **Aplicar todos os aptos desta prévia** para abranger
   todas as páginas. Digite `APLICAR` e confirme **Aplicar complementos
   revisados**. A coleta sozinha não ativa os dados.
4. Confira o recibo e **Baixar backup verificado**. A versão aceita aparece
   nas estatísticas e nas páginas nativas dos registros correspondentes.
   Para desfazer a ativação, use a recuperação da versão analítica anterior
   com `RESTAURAR`, conforme o procedimento acima.

### Preservação, identidade e retomada

O POST `/administration/openalex/enrichment/refresh-acervo` exige
administração e CSRF. Cria um `stats_scan` com `enrich_after=True`; a
conclusão do inventário e a criação da coleta completa `enrich_collect`
ficam na mesma transação. A fila SQL recupera o filho se houver interrupção
antes do despacho. Repetir a ação acompanha a atualização em andamento,
sem criar outra coleta; uma aplicação ou recuperação em execução também
leva ao acompanhamento pelo botão principal. A opção separada **Coleta a
partir de um retrato existente** continua disponível para o retrato atual
ou para o exemplo real de 100 obras.

Esta atualização mantém título, resumo, autores, ORCID, demais metadados
bibliográficos, arquivos, comunidades, publicação e acesso. Os complementos
permanecem na camada analítica aceita; não criam facetas na busca nativa
nem alteram seus documentos bibliográficos. Os índices SQLite de ID e DOI
de origem aceleram as verificações de identidade das próximas aplicações.

A seção **Topics e métricas OpenAlex** do registro aparece depois da
autorização da view nativa do InvenioRDM. A consulta confere o UUID, o ID
público e os identificadores DOI/OpenAlex correntes antes de mostrar a
versão aceita. Rascunhos em prévia, registros removidos e identidades
divergentes não exibem complementos. A leitura não ganhou endpoint público
adicional. Os controles de atualização continuam administrativos.

A página mostra tópico principal e hierarquia, citações na coleta, FWCI e
percentil em escala 0–100. Os detalhes expõem tópicos/pontuações, histórico
fornecido, fonte, datas, método e versão. Valores empilham no celular.
Ausência continua explícita e não significa zero; FWCI=1 é a referência
mundial da fonte. Citações e FWCI não são JIF. A classificação automática
OpenAlex não comprova identidade mineralógica.

### Recibo da aplicação real e validação

O estado anterior desta documentação — prévia de 100 obras e ponteiro
ativo NULL — descreve a entrega inicial preservada acima. A atualização
posterior está registrada em `output/openalex-acervo-20261026/`:

| Evidência | Resultado |
| --- | --- |
| Prévia completa | `1fabe509726f4a3f80c664b64505b7ac`, 5.645 aptos |
| Aplicação ativa | `c7b90ff39ed940a0a2837d0f656ec207`, `completed`, 5.645 aplicados, zero falhas |
| Preservação | Contagens e hashes de sete tabelas nativas e de arquivos inalterados |
| Backup ZIP verificado | `c7b90ff39ed940a0a2837d0f656ec207.zip`, 3.059.523 bytes |
| SHA-256 do ZIP | `171b67c3dbd7ff5ef47e5215a70dc17acc85dd292f3e48feb7cf7196ee4da152` |

`verified-acervo.json` confirma 5.636 obras com tópico principal/hierarquia
(9 ausentes), 5.181 com FWCI (464 ausentes), 5.196 com percentil (449
ausentes), citações disponíveis nas 5.645 e lista de Topics fornecida nas
5.645. Lista fornecida pode estar vazia, conforme a distinção documentada.
Também registra PT/EN com HTTP 200, administração anônima com 403,
ausência de CSRF com 400, aplicação repetida levando à mesma versão ativa
e métricas públicas sem controles administrativos.

`acervo-tests.log` contém cinco testes aprovados da leitura dos
complementos; `enrichment-tests.log` contém quinze testes aprovados.
`refresh-chain.json` confirma a cadeia inventário → prévia completa,
checkpoint atômico e repetição sem novo filho; os jobs de teste foram
revertidos, sem chamadas de rede. `csv-check.json` confirma consulta e
exportação iguais em dois recortes da versão ativa: 5.645 obras sem filtro
(5.181 FWCI, 5.645 linhas CSV) e 2.171 na área OpenAlex
`https://openalex.org/fields/25` (2.048 FWCI, 2.171 linhas CSV).
`indexed-checks.json` registra 5.645 verificações de identidade em 0,0038 s
e uso dos índices SQLite de ID/DOI. Esse ensaio não mede o tempo da coleta
ou da aplicação completa.

As seis capturas em `.impeccable/review/openalex-acervo/` cobrem busca,
atualização e a região de métricas do registro em desktop e celular.
`finish-review.md` na pasta de evidências registra `ship`, sem correções;
o detector fornecido contém `[]`. São evidências existentes verificadas
para esta documentação, sem nova execução de navegador, detector ou testes.
