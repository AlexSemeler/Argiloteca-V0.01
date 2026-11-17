# Revisão N/G/C dos 673 arquivos recuperados

Revisão realizada em 20/10/2026. **Nenhum novo trio foi integrado às Análises ou ao painel DRX**, pois os dois candidatos encontrados ainda têm vínculos ambíguos entre preparos. Os 673 arquivos continuam restritos. Nenhuma classificação foi recalculada e nenhum registro foi publicado.

## Escopo e resultado

Foram conferidos os 673 derivados recuperados, sua correspondência restrita com o corpus de 9.948 RAWs e os possíveis companheiros já anonimizados na primeira etapa. O agrupamento considera o diretório de origem para evitar unir códigos repetidos de projetos diferentes.

| Conferência | Resultado |
|---|---:|
| Arquivos recuperados revisados | 673 |
| Grupos existentes associados | 598 |
| Arquivos com preparo N explícito no nome | 85 |
| Arquivos com preparo G explícito no nome | 88 |
| Arquivos com preparo C explícito e separado no nome | 0 |
| Arquivos com preparo indeterminado segundo a regra estrita | 500 |
| Candidatos adicionais encontrados por nomes concatenados | 2 grupos, 10 arquivos |
| Novos trios com vínculo confirmado e sem escolha ambígua de versão | 0 |
| Arquivos novos integrados | 0 |
| Arquivos recuperados mantidos restritos | 673 |

Os 598 grupos estritos se distribuem em 499 arquivos isolados com preparo indeterminado, 73 pares N/G, 14 arquivos G isolados, 11 arquivos N isolados e um grupo N/G/indeterminado. Não foram encontrados companheiros que completem esses grupos no restante do corpus.

Também foram inspecionados os campos de amostra documentados nos cabeçalhos. Foram encontrados três marcadores N explícitos e nenhum novo marcador C explícito. Para layouts sem campo de amostra documentado, não se interpretaram bytes reservados como identificação de preparo.

## Dois candidatos que precisam de confirmação

A busca adicional removeu apenas diferenças de separador para localizar possíveis nomes N/G/C concatenados. Essa busca produz candidatos para revisão, sem reatribuir os códigos anônimos ou confirmar vínculos automaticamente.

| Candidato | Arquivos de origem | Versões N com dados distintos | Versões G com dados distintos | Versões C |
|---|---:|---:|---:|---:|
| A | 5 | 2 | 1 | 1 |
| B | 5 | 2 | 2 | 1 |

No candidato A, as duas versões G têm os mesmos eixos, intensidades e comprimento de onda; as duas versões N têm intensidades diferentes. No candidato B, tanto N quanto G têm versões com intensidades diferentes. Não há evidência suficiente para tratar todas essas versões como cópias intercambiáveis ou escolher uma delas como companheira do C.

Em ambos, os arquivos N/G declaram aproximadamente 1,54056 Å e os arquivos C aproximadamente 1,78901 Å. Um trio com radiações diferentes precisa de vínculo de preparo confirmado e comparação que considere o comprimento de onda de cada curva. Não se presumiu Cu para o C nem se deslocou seu eixo para fazê-lo coincidir com N/G.

Os nomes originais, os códigos anônimos correspondentes, os hashes das séries, formatos e comprimentos de onda ficam somente em `output/recovered-trios-20261020/restricted/candidate-review.json`. Os nomes não foram propagados ao relatório público do projeto.

Para concluir a integração desses candidatos, falta uma ficha de preparo, vínculo de pacote analítico ou informação curatorial que indique quais versões N e G pertencem a cada C. A confirmação também deve esclarecer a diferença de radiação. Foi solicitada essa informação ao usuário.

## Preservação e validação

Todos os 9.948 originais foram novamente conferidos por SHA-256. A auditoria fechou as contagens dos 673 recuperados e comparou as séries dos dez arquivos candidatos sem modificar os dados. Foram preservados os registros de classificação, as regras científicas, os arquivos de recuperação e a configuração de publicação.

As consultas somente leitura e a conferência de hashes estão registradas em `output/recovered-trios-20261020/preservation.json`. A homologação mantém os 1.226 registros públicos e os 1.224 RAWs dos 408 trios anteriormente habilitados. Não houve alteração de frontend ou de parser nesta revisão; não foi necessário repetir a suíte de 282 testes da recuperação para uma auditoria sem mudança de implementação.

O roteiro reproduzível está em `output/recovered-trios-20261020/audit_candidates.py`; os totais estão em `review-summary.json`. As evidências com identificadores originais estão em diretório 0700, com arquivos 0600, excluído do Git. Nenhuma chamada de escrita ou publicação foi feita.
