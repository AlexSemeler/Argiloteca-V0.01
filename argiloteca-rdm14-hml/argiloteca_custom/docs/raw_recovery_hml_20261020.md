# Recuperação dos 675 arquivos sem anonimização

Investigação e recuperação concluídas em 20/10/2026 na homologação. **673 arquivos foram recuperados e anonimizados; dois arquivos estão vazios.** Nenhum original foi regravado, nenhuma classificação existente foi alterada e nenhum registro foi publicado.

Somando os derivados da primeira etapa, **9.946 dos 9.948 arquivos de origem agora têm um derivado anonimizado**. Esse total inclui um RAS e um GSAS, que passaram a usar as extensões correspondentes ao conteúdo. São 9.944 derivados binários `.raw`, um `.ras` e um `.gsa`.

## Diagnóstico e correções

| Conteúdo identificado | Arquivos | Tratamento |
|---|---:|---|
| Bruker RAW legado, uma faixa | 379 | Leitura do início angular no campo correto; cabeçalho anonimizado, vetor binário preservado |
| Bruker RAW2, cabeçalho de faixa de 60 bytes | 256 | Leitura do início angular e da radiação declarados; cabeçalho anonimizado |
| Rigaku RAW com assinatura FI/BU, variante nova | 32 | Layout identificado no importador do Profex; nomes e textos removidos |
| Bruker RAW4, uma faixa angular acoplada | 2 | Segmentos de metadados saneados; faixa e vetor preservados |
| Bruker RAW1.01 com varredura em torno de zero | 2 | Anonimização sem deslocar os ângulos negativos; retenção para revisão do tipo de medição |
| Rigaku RAS, originalmente com extensão `.raw` | 1 | Derivado `.ras`, metadados pessoais/de origem eliminados; três colunas numéricas preservadas |
| GSAS ESD, originalmente com extensão `.raw` | 1 | Derivado `.gsa`, título anonimizado e contagem de registros corrigida; intensidades e incertezas preservadas |
| Arquivos vazios | 2 | Zero bytes também na cópia restrita; sem dados para reconstrução |
| **Total** | **675** | **673 recuperados; dois sem dados** |

A maioria das recusas vinha de limitações de leitura e anonimização, sem evidência de corrupção do vetor. No RAW legado, o início angular está no offset 24; no RAW2, no offset 272. Os campos de tempo por passo não são ângulos. Todos os layouts aceitos foram delimitados por assinatura, tamanho de cabeçalho, número de faixas, pontos e comprimento efetivo do arquivo.

Os dois RAW1.01 antes recusados têm 101 pontos entre −0,2° e +0,2°. Esse intervalo foi preservado. Eles continuam retidos para verificar se são medições de alinhamento; a recuperação não os transforma em difratogramas adequados à identificação mineralógica.

O GSAS contém 35.666 pares intensidade/incerteza. O cabeçalho declarava 7.133 registros; o conteúdo contém os 7.134 registros necessários. O derivado corrige esse contador e completa o preenchimento em branco do último registro, de 48 para 80 colunas. Não foram acrescentados valores numéricos. A coordenada nativa foi mantida: falta a informação instrumental que confirme se a unidade é CW ou TOF. Nenhum comprimento de onda foi presumido para esse arquivo.

O RAS mantém ângulo, intensidade e terceira coluna de atenuação, sem aplicar automaticamente uma correção de intensidade. Os campos numéricos selecionados são preservados; textos livres e datas não são propagados. Sua codificação original contém caracteres não ASCII em metadados descartados, sem afetar as linhas numéricas.

Foram preservados os comprimentos de onda declarados, inclusive **86 arquivos com aproximadamente 1,78901 Å**. Os campos Kα1 não foram convertidos automaticamente em uma radiação efetiva nem substituídos por Cu Kα. As classificações anteriores não foram recalculadas nesta etapa.

## Onde estão os resultados

Os derivados estão em:

`argiloteca-rdm14-hml/data/drx/recovery-v1-20261020/files/`

As curvas numéricas, incertezas, dados auxiliares e metadados de recuperação estão em:

`argiloteca-rdm14-hml/data/drx/recovery-v1-20261020/curves/`

O inventário é `argiloteca-rdm14-hml/data/drx/recovery-v1-20261020/index.json`. Ele usa os códigos anônimos já atribuídos e registra `publication_eligible: false` para todos os itens. Diretórios têm permissão 0700 e arquivos 0600; o lote foi excluído do Git e não está montado nos serviços web.

A correspondência restrita, os hashes e os detalhes das correções estão em `output/raw-recovery-20261020/restricted/recovery-ledger.json`. Os backups integrais anteriores continuam em `output/raw-lifecycle-20261020/restricted/original-raw/`.

**Recuperação não equivale a liberação pública.** Os 673 arquivos continuam em revisão quanto a preparo, formação de trio N/G/C, protocolo de aquisição e unidades instrumentais. Os novos leitores foram instalados como ferramentas de recuperação e não foram ligados automaticamente ao classificador ou ao painel público. O snapshot público continua contendo os 408 trios anteriormente validados, com 1.224 RAWs. As regras nativas de publicação não foram ampliadas.

## Implementação

O leitor puro é `argiloteca_drx_core/raw_recovery.py`: recebe bytes, valida limites antes de ler vetores e produz derivados determinísticos. O adaptador preserva a taxonomia de erros do parser. Ele aceita somente as variantes verificadas; não representa suporte geral a todos os formatos comerciais chamados RAW.

O comando administrativo é:

```console
python -m argiloteca.drx.services.raw_recovery_batch \
  --manifest output/raw-recovery-20261020/restricted/input-manifest.json \
  --destination <novo-diretorio-de-recuperacao> \
  --restricted <diretorio-restrito-de-auditoria>
```

O destino precisa ser novo. O comando confere os hashes dos originais e dos backups antes e depois, recusa sobrescrita, relê todos os derivados e testa a idempotência da anonimização. Não chama serviços de publicação ou reclassificação do Invenio.

Os únicos bindings adicionados aos serviços são os dois módulos de recuperação. O diretório recuperado permanece fora dos mounts web. Os módulos anteriores de parser, classificação e publicação mantiveram os hashes da execução anterior.

## Evidências de validação

- **673 arquivos** comparados nos originais e nos derivados com leitores independentes: 639 com xylib, 32 com a rotina Rigaku do Profex, um com scattio e um com a rotina ESD do GSAS-II.
- Diferença máxima de intensidade: **zero**. Diferença máxima de eixo: **1,4210854715202004 × 10⁻¹⁴**, por ordem de operações em ponto flutuante. Atenuadores e incertezas foram preservados.
- **673 derivados** relidos no Python 3.14 da homologação, em contêiner sem rede e com mounts somente leitura; arrays, comprimentos de onda e hashes conferidos com os sidecars.
- **282 testes aprovados, três ignorados e 11 avisos** na suíte instalada. Foram cobertos truncamento, bytes adicionais, limites, variantes desconhecidas, privacidade, idempotência, correção limitada de GSAS e manutenção do bloqueio de publicação.
- **9.948 originais** conferidos por SHA-256 e preservados. Os 675 backups correspondentes também foram conferidos.
- Consultas somente leitura confirmaram **1.226 registros públicos**, **1.224 RAWs públicos**, snapshots e configuração de publicação inalterados. UI, API, worker e agendador terminaram saudáveis.

As evidências estão em `output/raw-recovery-20261020/`: `independent-validation.json`, `runtime-validation.json`, `installed-regression.log`, `original-integrity.json`, `live-validation.json`, `services.log` e `validation.json`.

## Fontes dos layouts

- [xylib — leitor Bruker RAW](https://github.com/wojdyr/xylib/blob/199a1ed/xylib/bruker_raw.cpp), com referências aos manuais DIFFRAC-AT e DIFFRACplus no cabeçalho. A rotina de leitura foi compilada sem alterações; o harness limita o registro a Bruker e adapta a detecção de endianness à plataforma de teste.
- [Profex — distribuição oficial do código 5.7.2](https://www.profex-xrd.org/wp-content/uploads/2026/08/profex-5.7.2.tar.gz), arquivo `libXrdIO/import/rigakurawimport.cpp`, rotina `loadNew`. O harness conserva essa rotina e substitui apenas as classes Qt de transporte por estruturas de teste. O suporte Rigaku é baseado em engenharia reversa; permanece limitado à variante FI/BU conferida.
- [scattio — leitor Rigaku RAS](https://github.com/scattering/scattio/blob/master/python/scattio/rigaku.py), função de parsing usada sem executar helpers de impressão de metadados.
- [GSAS-II — leitor ESD](https://github.com/AdvancedPhotonSource/GSAS-II/blob/master/GSASII/imports/G2pwd_fxye.py), rotina usada em isolamento da interface gráfica. A comparação numérica não foi usada para inferir a unidade física do GSAS recuperado.

Cópias e hashes das fontes consultadas ficam em `output/raw-recovery-20261020/sources/` e `source-provenance.json`. Nenhum arquivo da Argiloteca foi enviado a um serviço externo.
