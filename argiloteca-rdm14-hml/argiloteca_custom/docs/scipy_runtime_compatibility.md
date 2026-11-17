# SciPy na homologação — importação padrão corrigida

Aplicado em 20/10/2026 aos serviços **web-ui e web-api** da homologação. O contexto N/G/C continua experimental, executado explicitamente em modo sombra. Não houve alteração de classificações, regras científicas, registros ou publicação.

## Diagnóstico e correção

O SciPy estava instalado e compatível segundo seus metadados; a importação de `scipy.signal` alcançava `scipy.stats`, cuja inicialização gera exemplos de documentação. Nesse caminho, `Normal._moment_central_formula` avalia `order % 2`. Neste ambiente, a operação de resto decimal do NumPy não terminava.

Ambiente observado: Python 3.14.7, Linux amd64 executado via Rosetta, glibc 2.41, NumPy 2.5.3, SciPy 1.18.1. Em subprocessos com limite de tempo:

- `2.0 % 2`, `math.fmod(2., 2.)`, `np.fmod(2., 2.)` e o resto de inteiros funcionavam.
- `np.float64(2) % 2` e o resto de arrays decimais travavam.
- Desativar instruções opcionais da CPU ou trocar o núcleo do BLAS não resolveu.
- NumPy 2.4.6 e 2.5.4, testados em diretórios separados, também não concluíram a importação padrão do SciPy neste ambiente.
- **NumPy 2.3.5 com o mesmo SciPy 1.18.1 resolveu a operação e a importação padrão**, incluindo a geração integral dos exemplos de documentação.

Isso caracteriza uma incompatibilidade reproduzida nesta combinação de ambiente/binários; não demonstra uma falha universal dessas versões do NumPy. A hipótese de defeito em `fmod` da glibc foi descartada pelos controles. Não houve tentativa de alterar funções matemáticas, substituir resultados ou confirmar uma causa de compilação sem evidência.

A dependência foi fixada como `numpy==2.3.5` em `argiloteca_custom/pyproject.toml`. O novo `uv.lock` altera **somente a versão do NumPy**, mantendo SciPy 1.18.1 e todas as outras versões. A metadata do pacote Argiloteca no lock acompanha o novo requisito. O resolvedor confirmou os requisitos do SciPy (`numpy>=2.0,<2.8`), e `uv pip check` passou com os 284 pacotes instalados.

A [documentação de `numpy.remainder`](https://numpy.org/doc/stable/reference/generated/numpy.remainder.html) descreve a operação testada. O [código do NumPy](https://github.com/numpy/numpy/blob/v2.5.3/numpy/_core/src/npymath/npy_math_internal.h.src) ajuda a distinguir resto e `fmod`; os resultados deste diagnóstico derivam dos controles executados localmente, não de uma alegação de correção publicada pelo projeto NumPy.

## Aplicação persistente

Foi criada uma imagem derivada da imagem existente, atualizando apenas NumPy e copiando o lockfile, o manifesto de dependências e a verificação de importação. O frontend, código científico e dados não foram reconstruídos nem substituídos.

- Imagem validada: `argiloteca-rdm14-hml:14.0.4-scipy-verified`.
- A tag normal `argiloteca-rdm14-hml:14.0.4` aponta para a imagem validada.
- Imagem anterior preservada: `argiloteca-rdm14-hml:scipy-baseline-20261020`.
- Receita da atualização limitada: `docker/scipy-compat.Dockerfile`, com contexto mínimo e `--platform linux/amd64`.
- O Dockerfile principal também verifica a importação após `uv sync --frozen`, protegendo futuras reconstruções completas.

Foram recriados somente web-ui e web-api. Seus comandos, variáveis de configuração e destinos de montagem foram comparados antes da atualização; não houve diferenças. O proxy recebeu `nginx -s reload` para resolver novamente os endereços dos serviços recriados. Ambos ficaram saudáveis, e a consulta pública de registros voltou a responder com 1.226 registros.

Workers e agendador não foram reiniciados; não foram enfileiradas tarefas. Mantêm a imagem anterior enquanto estiverem em execução. A tag corrigida e o lockfile serão utilizados numa futura recriação. O diagnóstico isolado do worker revelou um problema anterior de carregamento de `resolve_snapshot_raw_download`, e seu healthcheck permanecia não saudável. A configuração atual também acrescentaria montagens científicas a esses processos se fossem recriados. Essa atualização de código/processos de tarefas foi mantida fora do escopo para não acionar processamento ou alterações de dados durante este reteste.

## Verificação sem contorno de teste

O script `scripts/check_scientific_runtime.py` inicia um interpretador novo, com limite de 30 segundos. Testa:

1. resto decimal escalar e em arrays, incluindo operandos negativos;
2. importação padrão de `scipy.signal` e `scipy.stats`;
3. variância e quarto momento da distribuição Normal;
4. detecção de picos e preservação de um polinômio pela suavização;
5. presença integral dos exemplos de documentação e ausência do antigo carregador de contorno.

Não modifica módulos, funções, documentação ou importadores. O tempo limite encerra o filho travado e faz a construção falhar, evitando uma imagem aparentemente saudável com a mesma falha.

Após a aplicação, sem `PYTHONPATH` alternativo para NumPy e sem opções extras de CPU/BLAS:

| Serviço | NumPy / SciPy | Importação e controles | Tempo |
|---|---|---|---:|
| web-ui | 2.3.5 / 1.18.1 | aprovados; documentação intacta | 1,17 s |
| web-api | 2.3.5 / 1.18.1 | aprovados; documentação intacta | 1,26 s |

Os hashes de **1.095 arquivos Python e bibliotecas compartilhadas do SciPy** coincidem com a imagem anterior. A correção não é uma instalação permanente do antigo contorno de documentação.

Comando para repetir a verificação normal:

```sh
docker exec argiloteca-rdm14-hml-web-ui-1 \
  python /opt/invenio/src/scripts/check_scientific_runtime.py --timeout 30
```

## Reteste CPAA e regressão

A suíte foi executada novamente na imagem instalada: **232 aprovados, 3 ignorados e 10 avisos preexistentes**, sem falhas, em 24,03 s. Não utilizou `run_regression_doc_workaround.py`, `scipy_docs_test_hook.py` ou substituição de funções. O caminho adicional da suíte contém apenas o executor pytest; NumPy e SciPy vêm do ambiente instalado.

Os **30 grupos / 89 RAWs** foram processados novamente com o executor `evaluate_runtime_standard.py`, que não importa o contorno antigo. Foram mantidos:

- as mesmas impressões digitais;
- a mesma ordem das candidatas em N, G e C;
- os mesmos estados de compatibilidade/inconclusão de família;
- a mesma quantidade de picos por perfil.

A maior diferença de posição/proeminência/largura foi **4,55 × 10⁻¹⁵**, inferior à tolerância absoluta predefinida de 10⁻¹⁰. Os escores também passaram na tolerância predefinida de 10⁻⁸. Não foram ajustados limiares ou resultados esperados para obter concordância.

A interpretação científica permanece a do [relatório N/G/C](reference_pilot_ngc_shadow.md): 106182/106183 com candidata da família esmectita e trajetória compatível; clorita preservada em 19.008.006; 19-146 ainda inconclusiva. A concordância com Fase 1 continua 26/30, sem validação cega ou confirmação curatorial. A diferença de ordenação em 19.008.005 permanece documentada.

## Integridade

- API ativa continua em `pilot-position-coverage-v1`, modo sombra, com o mesmo índice e resposta de status.
- V1, V2, novo contexto N/G/C, parser experimental e canônico, serviço temporário e NGC anterior preservaram seus hashes.
- Planilha, RAR e os 89 RAWs preservaram os hashes.
- Snapshot da homologação: **103.197.696 bytes**, SHA-256 `1bc32af5dcea99d24b10f732591c94ee1847600b58fc379f0d1d7b43e580168e`, igual antes e depois.
- Contagem pública: **1.226 → 1.226**.
- Nenhuma chamada de criação, atualização ou publicação de registro foi realizada. Os testes somente calcularam resultados em memória e gravaram evidências no diretório do experimento.

## Evidências reproduzíveis

Na raiz Git, `output/scipy-import-fix-20261020/` contém as sondagens com timeout, comparação do lockfile, receita/contexto de imagem, logs de construção/aplicação, verificações de importação dos dois serviços, hashes do SciPy, suíte, resultados CPAA e comparações de integridade.

Executores da avaliação: `runtime-test-harness/run_regression.py` e `evaluate_runtime_standard.py`, usando as cópias de fixtures preservadas e módulos científicos congelados. A verificação `verify_cpaa.py installed-cpaa-results.json` compara os resultados com o protocolo anterior, sem alterar os dados de referência.

A imagem anterior foi preservada para reversão de dependências se necessário. A correção não promove o contexto N/G/C ao fluxo normal nem autoriza reclassificação de registros existentes.
