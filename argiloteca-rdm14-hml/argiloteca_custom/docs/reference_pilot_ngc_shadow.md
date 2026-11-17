# Correção experimental do eixo RAW1.01 e contexto N/G/C

Implementação preparada em 20/10/2026 para investigar a regressão da V2 em clorita e as amostras CPAA 106182/106183. **Execução explícita em modo sombra; sem rota HTTP, integração automática, gravação, publicação ou substituição da V1/V2.**

## O que mudou

Dois módulos novos, sem editar os leitores e serviços existentes:

- `argiloteca_drx_core/raw101_shadow.py`: adaptador restrito de RAW1.01, ativado apenas com `enabled=True`. Lê o início de 2θ declarado no cabeçalho do intervalo como float64, valida contagem, tamanho exato, limites, eixo, comprimento de onda e intensidades. Aceita somente arquivos concluídos com um intervalo, cabeçalho de 304 bytes e nenhum cabeçalho suplementar; os demais layouts são recusados. Não regrava RAW nem aplica ajuste por quartzo/glicolação.
- `argiloteca/drx/services/reference_pilot_ngc_shadow_service.py`: recebe um único grupo explícito N/G/C de bytes, rejeita preparações repetidas e conteúdo duplicado e retorna as candidatas da **V2 congelada, sem mudar sua ordenação**, em cada curva. Acrescenta contexto separado de compatibilidade das famílias clorita/esmectita, com observações, lacunas, fontes e impressão digital. Não confirma espécie nem infere porcentagem.

Nenhum arquivo novo é importado pelas rotas, parser canônico ou serviço de upload. A API normal continua na regra V1 `pilot-position-coverage-v1`, em modo sombra. A V2 `pilot-cosine-peak-evidence-v2` permanece idêntica, SHA-256 `963c19f3495cf773ea7dcbea11d191ae4f71fbdbf22e48034e6ba87e2e18ba5b`.

## Causa identificada no eixo

O leitor canônico de RAW1.01 usa o float32 de endereço absoluto `0x388` (904) como início do eixo. No layout documentado esse endereço corresponde ao **tempo por passo**, na posição 192 do cabeçalho do intervalo. O início de 2θ fica na posição 16 desse cabeçalho, endereço absoluto 728, e é float64. O passo angular em 888 e o vetor de intensidades em 1016 já coincidiam com os arquivos examinados.

A distinção é sustentada pelo [leitor Bruker do xylib](https://github.com/wojdyr/xylib/blob/master/xylib/bruker_raw.cpp), que remete ao apêndice A do manual DIFFRAC plus XCH, e pela leitura de início de 2θ usada no [importador RAW do GSAS-II](https://gsas-ii.readthedocs.io/en/latest/_modules/GSASII/imports/G2pwd_BrukerRAW.html). O GSAS-II tem uma estratégia diferente para cabeçalhos suplementares: esta proposta não generaliza esse ponto e aceita apenas o layout simples cuja contagem fecha exatamente nos bytes CPAA.

Nos quatro trios de foco, o início declarado é 2,3°, enquanto o tempo por passo é 2 s em N/C e 3 s em G. Assim, o eixo antigo deslocava N/C em −0,3° e G em +0,7° em relação ao cabeçalho. A heurística de temporários que subtrai 1° em certos G ameniza parte da discrepância, mas não equivale a ler o campo correto. Ela permanece inalterada no serviço existente.

Nos 89 arquivos, 68 eixos diferem entre as leituras; 21 coincidem por igualdade numérica entre tempo e início. Os deslocamentos do novo eixo em relação ao antigo são: 36 arquivos +0,3°, 18 −0,7°, 10 −1°, 4 +1°, 21 zero. As contagens declaradas fecham em todos os arquivos; **todas as intensidades e todos os bytes originais foram preservados**. Ler um eixo declarado não prova calibração instrumental; ainda é necessária conferência externa do instrumento/exportação antes de promover a mudança.

## Por que a clorita perdeu posição

Na amostra 19-146, sob o eixo antigo, clinochlore tinha 18/18 linhas posicionais coincidentes. A V1 lhe atribuía cobertura 1,0. A V2 troca essa medida por concordância ponderada de amplitudes e proximidade: albita ficou com 0,17570895 e clinochlore com 0,12714679. A maior contribuição da albita veio de coincidências em 28,12°, 27,82° e 21,94°. Isso explica a troca de ordem; **não confirma a presença ou predominância de albita**.

O índice contém estruturas ideais com intensidades calculadas; a preparação orientada e o tratamento térmico alteram intensidades. O [manual USGS sobre cloritas](https://pubs.usgs.gov/of/2001/of01-041/htmldocs/clays/chlor.htm) descreve a estabilidade das posições basais e a alteração de intensidades com aquecimento. Portanto, o escore da V2 deve permanecer evidência estrutural auxiliar, separado do comportamento N/G/C.

O eixo corrigido sozinho não recupera o primeiro lugar de 19-146: clinochlore continua em segundo (0,11702784), após albita (0,16084757). No G há suporte parcial em aproximadamente 14,24 / 7,08 / 3,55 Å; em N e C os sinais basais coerentes são insuficientes para o novo controle de proeminência. O resultado preparado é **inconclusivo, requer revisão do RAW, do preparo e do protocolo**, sem excluir clorita ou mudar a Fase 1. Não foram criados exceções por ID, pesos que favoreçam a classe esperada ou alinhamento por rótulo.

O controle 19.008.006 mantém clinochlore em primeiro e apresenta basal de aproximadamente 14 Å estável nos três preparos, com companheiras em N/G. O contexto retorna `chlorite_group: compatible`, sem confirmar clinochlore ou composição monominerálica.

## 106182 e 106183

Com o eixo declarado e a mesma V2:

| Amostra | Primeira candidata no eixo antigo | Primeira candidata no eixo declarado | N → G → C, Å, por máximos de perfil suavizado |
|---|---|---|---|
| 106182 | Sepiolite; montmorillonite fora das 8 | Montmorillonite, escore 0,61134535 | 15,17 → 16,92 → 9,65 |
| 106183 | Sepiolite; montmorillonite fora das 8 | Montmorillonite, escore 0,55457034 | 15,23 → 16,92 → 9,54 |

Ambos têm companheira de segunda ordem no G, em aproximadamente 8,47 e 8,43 Å. O contexto é compatível com **família das esmectitas**. O [manual USGS sobre esmectitas](https://pubs.usgs.gov/of/2001/of01-041/htmldocs/clays/smc.htm) descreve expansão por glicolação e contração por aquecimento. Isso não diferencia montmorillonita, beidellita, nontronita ou outros membros sem evidência adicional.

Os números de d variam ligeiramente entre máximos suavizados, picos RAW e ajuste ALS; eles são cálculos diferentes. Os valores da tabela são os que efetivamente sustentam a nova regra e estão registrados integralmente em `results.json`.

## Proteção contra máximos artificiais de janela

No fluxo antigo, uma busca direcionada seleciona, para N de 106182/106183, 14,86691 Å em 5,94° — a borda da janela de clorita, na encosta do pico largo principal. Isso pode virar suporte artificial para outra família. O novo contexto encontra máximos **no perfil inteiro** antes de procurar reflexões nas janelas; uma encosta monotônica na borda não constitui outro pico.

Parâmetros experimentais congelados antes da execução dos outros 26 controles CPAA:

- Savitzky–Golay de 9 pontos, polinômio 2; proeminência mínima de 2% da amplitude suavizada, largura mínima 3 pontos e distância mínima 0,18°.
- Clorita: basal 13,7–14,7 Å em N/G/C com proeminência mínima de 5%, variação máxima 0,5 Å e companheiras N/G em 6,9–7,3 e 3,50–3,56 Å. Intensidade relativa entre tratamentos não precisa ser constante.
- Esmectita: reflexões proeminentes de N 12–16,5 Å, G 16–18,5 Å e C 9,4–10,5 Å; expansão mínima 0,6 Å, contração mínima 1,5 Å; companheira G em metade de d001 ±0,35 Å. Para as três basais, proeminência mínima 10%.
- Trio incompleto não obtém suporte completo; ausência de suporte significa evidência insuficiente, não ausência de mineral. Duas famílias podem permanecer compatíveis em mistura.

**Essas tolerâncias e filtros são decisões de engenharia experimentais, não limites de identificação validados pela literatura.** Temperaturas de C, saturação, história de preparo e calibração não foram confirmadas. O contexto não cobre todas as esmectitas, interestratificados, vermiculitas nem caulinitas; não deve ser usado como classificador geral substituto.

## Resultado do reteste CPAA

A referência de comparação é a coluna Fase 1 indicada pelo usuário. O significado de X/? e a confirmação independente por especialista não foram estabelecidos. Todos os 30 grupos já foram examinados anteriormente: os 26 controles não constituem validação cega. Há 29 trios completos e um grupo sem C; os 89 arquivos não equivalem a 89 composições independentes.

A medida é concordância da primeira candidata de N com Fase 1, agrupando espécies de esmectita/clorita nas famílias correspondentes; não é estimativa de acurácia em produção.

| Grupo | V2 / eixo canônico antigo | Mesma V2 / eixo declarado |
|---|---:|---:|
| Caulinita | 11/17 | 16/17 |
| Esmectita | 6/11 | 9/11 |
| Clorita | 1/2 | 1/2 |
| Total, primeira candidata | 18/30 | 26/30 |
| Total, entre as 3 primeiras | 25/30 | 29/30 |
| Total, entre as 8 primeiras | 28/30 | 30/30 |

Nove amostras passam a concordar na primeira posição: CxRS10E, SRA200, SDE, 19.008.003, 19.008.004, PK101, PK2, 106182, 106183. Uma nova regressão permanece visível: **19.008.005**, Fase 1 caulinita, passa de kaolinite a clinochlore. Kaolinite permanece em segundo, com escores próximos (0,48470960 versus 0,49005252). A planilha também lista clorita como outra fase dessa amostra: a regressão é de concordância com Fase 1, não uma demonstração de mineral inexistente. O sentido de predominância de Fase 1 não foi confirmado. Não houve ajuste posterior dos parâmetros para esconder essa diferença.

O contexto N/G/C, avaliado separadamente, retorna compatibilidade em 6/11 esmectitas e 1/2 cloritas. Os outros casos ficam inconclusivos; não se converteu esse contexto em uma nova ordem de espécies. Os sete suportes correspondem à família indicada em Fase 1, mas isso não demonstra ausência de falsos positivos em misturas, minerais fora do índice ou outros instrumentos.

A comparação de V1 no eixo correto também está registrada: primeira posição 9/30, clorita 0/2. Os antigos 2/2 de clorita da V1 dependiam do eixo incorreto e não devem ser tratados como identificação confirmada.

## Como executar explicitamente

Na raiz Git, o experimento reproduzível está em `output/ngc-context-correction-20261020/`:

```sh
OPENBLAS_NUM_THREADS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=argiloteca-rdm14-hml/argiloteca_custom \
.tools/drx-reference-pilot/bin/python -m pytest --noconftest \
argiloteca-rdm14-hml/argiloteca_custom/tests/test_drx_ngc_shadow_correction.py -q

OPENBLAS_NUM_THREADS=1 PYTHONPATH=argiloteca-rdm14-hml/argiloteca_custom \
.tools/drx-reference-pilot/bin/python \
output/ngc-context-correction-20261020/evaluate_ngc_correction.py
```

O segundo comando verifica os hashes congelados e lê os arquivos extraídos auditados. Grava apenas resultados no diretório desse experimento. A comparação usa o índice local inalterado de 12 estruturas/10 minerais, não uma base AMCSD/COD completa.

Exemplo em memória (sem salvar):

```python
from argiloteca.drx.services.reference_pilot_ngc_shadow_service import (
    evaluate_reference_pilot_ngc_shadow,
)
result = evaluate_reference_pilot_ngc_shadow(
    [{"treatment": "N", "content": bytes_n},
     {"treatment": "G", "content": bytes_g},
     {"treatment": "C", "content": bytes_c}],
    enabled=True,
)
```

A ligação entre amostra e preparações deve ser auditada pelo chamador; o algoritmo não pode comprovar identidade material a partir do nome do arquivo. Nenhum ID CPAA ou Fase 1 é utilizado nas regras de execução.

## Evidências e limites de promoção

`candidate-freeze.json`, `axis-audit.json`, `results.json`, `comparison.csv`, `focus-diagnostics-strict.json`, `focus-trios.png/svg` e os logs de teste ficam no diretório do experimento. Os documentos `preservation-before.json`/`preservation-after.json` registram a integridade da V1, V2, parser, serviço temporário, NGC antigo, índice, snapshot, planilha/RAR e dos 89 RAWs.

Antes de promover ao fluxo normal: confirmar o eixo com exportação independente do instrumento; revisar 19-146 e a regressão 19.008.005; verificar protocolos N/G/C; ampliar estruturas de cloritas e esmectitas e testar amostras independentes, incluindo misturas e classes ausentes. Não foi feita migração de curvas armazenadas, de classificações ou de registros.

## Testes e verificação final

- Ambiente nativo: **28 testes novos aprovados**, sem falhas nem avisos.
- Ambiente da homologação: **232 aprovados, 3 ignorados e 10 avisos preexistentes**. Inclui regressão de ciência, parser, contratos, rotas, upload/temporários, V1, V2 e os novos controles.
- Reexecução das 30 séries / 89 RAWs em processo isolado da homologação: mesmas impressões digitais, mesma ordem das candidatas e mesmos estados de contexto; posições, proeminências e larguras concordam com o ambiente nativo em tolerância absoluta 1e-10.
- Snapshot de classificações da homologação antes/depois: 103.197.696 bytes, SHA-256 `1bc32af5dcea99d24b10f732591c94ee1847600b58fc379f0d1d7b43e580168e`.
- Contagem pública antes/depois: **1.226 → 1.226**. API confirmada em V1, modo sombra, com índice inalterado.
- V1/V2, parser canônico, serviço temporário, NGC antigo, índice, snapshot local, planilha/RAR e os 89 RAWs preservaram os hashes. Nenhuma chamada de criação, atualização ou publicação de registro foi feita.

### Limitação de execução no Docker

A primeira execução da suíte ficou presa na importação padrão de `scipy.signal`. Um processo diagnóstico independente mostrou a pilha em `scipy.stats._distribution_infrastructure._generate_example`, chamada por `_combine_docs` ao gerar a documentação de distribuições. Foram encerrados somente esses dois processos de teste; os serviços não foram reiniciados.

Para concluir os cálculos na homologação, `run_regression_doc_workaround.py` e `scipy_docs_test_hook.py` desativam **somente a geração dos exemplos de documentação**, por um carregador temporário em memória. Nenhuma rotina numérica foi substituída, nenhum arquivo do SciPy instalado foi editado e nenhuma dependência/configuração do serviço foi alterada. A suíte completa e os 30 retestes reais passaram nesse processo isolado. O log interrompido e a pilha diagnóstica foram preservados.

Na execução original, a importação padrão do SciPy no Docker ainda requeria correção. Essa limitação foi resolvida posteriormente nos serviços web, conforme a atualização abaixo. Os testes nativos usam a importação padrão, sem esse contorno. As versões dos dois ambientes e o procedimento exato estão nos arquivos `native-environment.json`, `runtime-environment.json` e nos inicializadores do experimento. Esta limitação não afeta a API V1 atual, que permanece ativa e inalterada.


## Atualização do ambiente — 20/10/2026

A importação padrão foi corrigida nos serviços web da homologação fixando NumPy 2.3.5, mantendo SciPy 1.18.1. Os 30 grupos CPAA e a suíte completa foram repetidos **sem o contorno de documentação**, com 232 aprovados e 3 ignorados. Candidatas, impressões digitais e estados N/G/C foram preservados; diferença numérica máxima de 4,55 × 10⁻¹⁵. A limitação de importação dos serviços web está superada; as limitações científicas descritas neste documento permanecem. Ver [correção do runtime e evidências](scipy_runtime_compatibility.md).
