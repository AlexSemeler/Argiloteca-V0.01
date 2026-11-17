# RAWs: reclassificação, anonimização e publicação por trio

Aplicado à homologação em 20/10/2026. Nenhum registro foi publicado automaticamente. A revisão dos registros já publicados foi incluída no escopo.

## Resultado do lote

O acervo canônico inspecionado foi `data/drx/raw-classificados`: 9.948 arquivos, com 82.365.711 bytes. Os arquivos temporários de usuários e as cópias de testes não foram incorporados ao acervo nem classificados como novos registros.

| Controle | Resultado |
|---|---:|
| RAWs processados e originais verificados por SHA-256 | 9.948 |
| RAWs analisados | 9.908 |
| Arquivos que não puderam ser analisados com segurança | 40 |
| Derivados RAW1.01 anonimizados | 9.273 |
| Formatos/cabeçalhos sem derivado RAW anonimizado validado | 675 |
| Medições interrompidas, analisadas mas retidas | 96 |
| Trios completos, distintos e anonimizados | 408 |
| RAWs desses trios disponíveis na consulta pública | 1.224 |
| RAWs retidos para revisão | 8.724 |
| Registros publicados consultados | 1.226 |
| Registros publicados com anexo ou referência RAW | 0 |

Os 675 arquivos sem derivado anonimizado compreendem 635 arquivos legados/RAW2 analisáveis, cujo saneamento binário não está validado, e os 40 arquivos que exigem revisão: 36 formatos não suportados, dois truncados/vazios e dois cabeçalhos com eixo físico inválido. Esses números se sobrepõem às categorias de retenção; não devem ser somados como grupos independentes.

A retenção é conservadora: N, G e C precisam estar explicitamente identificados no final do nome, no mesmo diretório e para a mesma base de amostra. Nomes iguais em diretórios diferentes não são unidos. Temperaturas ou letras soltas no nome não comprovam preparo. A composição mineralógica e o protocolo de preparação continuam dependendo da curadoria.

## Classificação e integridade científica

O classificador existente foi empacotado sem dependência de um script externo ausente na imagem. As oito funções matemáticas foram comparadas por AST com a implementação anterior e permaneceram iguais. Foram mantidas 86 entradas de referência, 71 delas com linhas d/I. Os parâmetros primários permanecem: até 14 picos, suavização de cinco pontos, distância mínima de 0,18°, proeminência relativa de 0,04, tolerâncias d de 0,08 Å e 2θ de 0,35°, até oito candidatos e Cu Kα de 1,54056 Å para a regra histórica.

Para o layout RAW1.01 comprovado, o eixo usa o início 2θ declarado no offset 728 e o passo no offset 888; o tempo por passo não é interpretado como ângulo. Os derivados e os uploads temporários deste layout, com a política ativa, não recebem o antigo deslocamento automático por preparo ou quartzo. Isto não substitui calibração instrumental independente.

O reprocessamento mudou o primeiro candidato em 7.540 arquivos e manteve-o em 2.408. Mudança de candidato não comprova melhora da identificação: muitos resultados anteriores usavam outro eixo. Os resultados são candidatos auxiliares, sem confirmação curatorial nem estimativa de abundância.

AMCSD/COD V2 foi calculado separadamente para 9.273 curvas; o contexto N/G/C foi avaliado para os 408 trios elegíveis. O piloto com cobertura reduzida não substituiu o classificador primário. As regras congeladas V2/N/G/C permanecem auxiliares, sem confirmar espécies ou sobrescrever laudos. A regressão das 30 amostras e 89 RAWs do CPAA manteve fingerprints, contexto de famílias e ordem de candidatos, com diferença máxima de score igual a zero em relação à execução instalada validada anterior.

## Anonimização e acesso

Os códigos públicos têm a forma `ARC-` seguida de 16 caracteres hexadecimais aleatórios; os arquivos publicáveis usam os sufixos `_N.raw`, `_G.raw` e `_C.raw`. Cada grupo recebe um código independente do nome ou da origem.

O derivado RAW1.01 elimina texto livre, datas, operador, identificação da origem/amostra e áreas reservadas. Conserva campos numéricos de aquisição documentados e os bytes de intensidade. A releitura verifica igualdade dos eixos e das intensidades. O hash público identifica o derivado, não o original. A correspondência com o nome, caminho e hash original fica restrita.

Há cópias integrais dos originais e dos snapshots anteriores em `output/raw-lifecycle-20261020/restricted`, com diretórios 0700 e arquivos 0600, fora dos mounts web e excluídas do Git. Os originais foram relidos e seus hashes conferidos após o lote. Os snapshots anteriores também permaneceram byte a byte iguais.

O snapshot ativo é a versão `data/drx/lifecycle-v1-20261020`. Somente os 408 trios validados são montados nos serviços. Os 8.724 arquivos retidos, suas classificações e os derivados anonimizados ainda incompletos ficam disponíveis no relatório restrito para revisão. Os serviços não recebem o diretório original nem os snapshots identificáveis. O importador persistente por arquivo/caminho foi bloqueado sob esta política; a comparação temporária continua disponível.

Os IDs dos snapshots foram renovados junto aos caminhos anonimizados. Links antigos desses snapshots não são redirecionados publicamente para evitar expor a correspondência. Seleções que ainda apontem para IDs anteriores precisam ser refeitas com os códigos atuais. Não houve limpeza dos arquivos temporários nem do armazenamento de sessão do navegador.

## Publicação nativa

`RawTrioPublicationComponent` executa antes dos componentes nativos de cópia/publicação de arquivos. A validação cobre publicação pela interface, API nativa e formulário científico, inclusive novas revisões de registros publicados. Salvar um rascunho incompleto continua permitido.

A validação lê os bytes dos anexos armazenados. Para cada amostra, exige exatamente N/G/C, nomes e cabeçalhos anonimizados, aquisição completa, comprimento de onda válido e perfis numéricos distintos. Rejeita duplicação de preparo, cabeçalho identificado, transferência incompleta e referências RAW locais/não anexadas. Quando presentes, os códigos de amostra e hashes dos metadados precisam corresponder ao arquivo anonimizado anexado. Registros sem RAW não precisam de trios.

A busca em todos os registros públicos não encontrou anexos RAW nem referências RAW em metadados/campos científicos. Não foi necessário editar ou republicar esses registros. A contagem pública permaneceu 1.226, e a tabela canônica de registros permaneceu com 2.167 linhas durante o teste nativo.

## Worker, tarefas e validação

O worker e o agendador foram recriados com a imagem científica corrigida e os mesmos bindings atuais da aplicação. A falha de importação vinha da combinação de código novo e módulos antigos no worker. NumPy 2.3.5 e SciPy 1.18.1 importam normalmente, sem alteração de docstrings ou contorno de teste.

Oito tarefas de diagnóstico completaram o percurso produtor → RabbitMQ → worker → backend, com respostas idênticas às entradas. Aplicação UI, API, worker e agendador terminaram saudáveis. Não foram forçadas tarefas periódicas de manutenção ou publicação.

A suíte final teve **255 testes aprovados, três ignorados e 11 avisos**. Os testes de compatibilidade legados usam a configuração legada explicitamente; os novos testes e o endpoint real verificam o modo ativo com o eixo declarado. A origem dos módulos instalados foi conferida.

O teste nativo criou três rascunhos sintéticos: publicação de trio incompleto e de nome identificável foi bloqueada; o trio completo foi reaberto e validado diretamente, sem invocar publicação. Uma barreira adicional no componente de cópia impediu que um defeito do teste publicasse qualquer arquivo. Todos os rascunhos sintéticos foram excluídos.

Também foram conferidos downloads anônimos, hashes, eixos, respostas das páginas Análises/DRX, bloqueio do importador por caminho e upload temporário pelo endpoint real, sem salvar ou publicar registros.

As evidências estão em `output/raw-lifecycle-20261020`: `public-integrity.json`, `installed-regression-final.log`, `native-validation-final.log`, `worker-probe.json`, `cpaa-parity.json`, `temporary-validation-final.log`, `live-validation.json` e `services-final.log`. A proveniência numérica e os hashes de código/referências constam de `run-provenance.json`.

## Operação e reversão

O comando offline é `python -m argiloteca.drx.services.raw_lifecycle_batch`, com argumentos obrigatórios `--source`, `--destination`, `--restricted`, `--reference` e `--runtime-root`. Exige um destino novo e recusa sobrescrever o backup de originais. Não acessa a função de publicação do Invenio.

Os arquivos anteriores e a configuração anterior foram preservados para reversão administrativa. O overlay `docker-compose.migrated.yml` seleciona o snapshot versionado; `invenio.cfg` ativa o componente de publicação. Reverter para o overlay anterior também reativaria os nomes identificáveis, portanto a reversão de anonimização precisa ser deliberada. Nenhuma reversão ou publicação foi executada.
