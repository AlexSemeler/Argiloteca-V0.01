# Piloto neural DRX offline

CNN pequena para ordenar dez padrões minerais de referência, mais a classe
`unknown`. Evidência experimental auxiliar: escores não são probabilidades
calibradas, composição quantitativa ou confirmação mineralógica.

**O candidato de 23/10/2026 foi reprovado nos testes medidos e não pode ser
ativado.** Os resultados das 899 curvas ficam em quarentena. Nenhum módulo deste
diretório é importado pelas rotas web, workers ou ArgiloClay.

O protocolo foi congelado antes das previsões. O treino usa somente dez estruturas
calculadas únicas AMCSD, com as duas representações COD duplicadas removidas.
As 899 curvas públicas, as 325 previsões históricas, os perfis RRUFF de teste e os
dados CPAA não entram no treinamento. As aumentações sintéticas não constituem
espécimes independentes. Não usar a acurácia sintética como acurácia em produção.

O modelo usa intensidade e máscara da faixa medida em canais distintos. O eixo
observado é preservado nos arquivos de origem; somente uma representação para a
rede é interpolada na grade 2–32°. Não há extrapolação, ajuste de posição por
mineral, alteração dos RAWs ou atualização automática de registros.

## Execução

Na raiz do projeto, usar o Python do ambiente registrado no manifesto. Nesta
máquina ele é `/Users/alexandresemeler/Argiloteca/argiloclay-rag/.venv/bin/python`.
O ambiente do Invenio não precisa receber Torch para servir o índice atual.

```sh
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/prepare.py
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/train.py
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/train.py --run-name reproduction
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/evaluate.py
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/infer.py
python argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot/release_gate.py
```

Preparação e treinamento recusam sobrescrever protocolo/checkpoint. Uma versão
seguinte precisa de outro diretório de saída e outro protocolo, preservando esta
avaliação. Não editar os critérios congelados para fazer o candidato passar.
`release_gate.py` termina com código **3** quando reprovado e não cria índice
de produção, não transfere arquivos e não altera Compose.

```sh
python -m unittest discover \
  -s argiloteca-rdm14-hml/argiloteca_custom/scripts/neural_drx_pilot \
  -p 'test_*.py' -v
```

`model.py` define arquitetura, classes e transformação. `weights.pt` contém
somente o `state_dict`; o carregador verifica hash e usa `weights_only=True`.
`inference_runtime.py` avalia os mesmos valores dos parâmetros em float64 para
reduzir diferenças numéricas entre lotes. Isso não muda os pesos treinados.

## Limites e continuidade

O treino representa padrões ideais de pó. Ele não cobre automaticamente montagem
orientada, hidratação, misturas e os efeitos N/G/C. A classe desconhecida gerada
com ruído/misturas sintéticas não cobriu adequadamente minerais reais ausentes.
É necessário ampliar o treinamento com medições e rótulos independentes,
preservar trios e espécimes no mesmo conjunto e reservar novos dados de teste.
Os testes já examinados passam a ser controles de regressão em outra iteração.

A planilha de curadoria preparada em `output/neural-replacement-20261023` possui
rótulos vazios, IDs públicos e hashes. Ela não altera registros nem confirma
minerais. A autoria, evidência e nível taxonômico precisam acompanhar cada revisão.

Fontes: [formatos RRUFF/AMCSD](https://www.rruff.net/help/zip-download/) e
[reprodutibilidade PyTorch](https://docs.pytorch.org/docs/2.14/notes/randomness.html).
As citações e hashes de cada estrutura estão em `training-references.json`.
