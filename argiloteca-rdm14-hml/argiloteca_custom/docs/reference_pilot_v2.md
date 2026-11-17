# Correção experimental do piloto de referências — V2

`reference_pilot_v2_service.evaluate_reference_pilot_v2` é uma função de avaliação
explícita, desabilitada por padrão, que sempre produz evidência em modo sombra.
Não é chamada pelas rotas ou pelos uploads existentes. A V1 continua ativa e seu
código não foi alterado. Nenhum resultado desta função é persistido em registros.

## Problema e alteração

A cobertura posicional da V1 pode atribuir escore 1 a duas coincidências fracas
em uma curva curta e ruidosa. A V2 mantém detector, limites, tolerância de 0,25°,
associação individual de picos e mínimo de duas correspondências. Muda a ordenação
para concordância conjunta das intensidades, com normalização L2 de ambos os lados:

```
sum(r_i * o_j * max(0, 1 - delta_2theta / 0.25))
------------------------------------------------
       sqrt(sum(r_i²)) * sqrt(sum(o_j²))
```

`r_i` são intensidades calculadas das linhas dentro da faixa medida; `o_j` são
amplitudes observadas acima do mínimo da curva. Linhas/picos não associados
contribuem para as normas, mas não para o produto. A normalização não estima fundo
físico. A correção não muda os pares XY, usa todas as referências antes de limitar
a lista a oito e mantém variantes AMCSD/COD como uma hipótese, sem votos extras.

## Contrato explícito

- Schema: `argiloteca.drx.reference_pilot.v2`.
- Regra: `pilot-cosine-peak-evidence-v2`.
- Escore: `paired_peak_intensity_cosine_not_probability`.
- Política: `auxiliary_candidates_only_no_reclassification`.
- `positional_coverage` retém a proporção posicional para inspeção; não é o escore.
- `score_components` e contribuições por correspondência permitem reproduzir o
  cálculo; `strongest_reference_line_unmatched` expõe modelos sem sua linha mais
  intensa observável, sem promover automaticamente outra espécie.
- Fingerprint inclui a regra, dados, radiação, parâmetros e hash do índice.

```python
from argiloteca.drx.services.reference_pilot_v2_service import evaluate_reference_pilot_v2

evidence = evaluate_reference_pilot_v2(
    two_theta, intensity, wavelength_angstrom=1.5406,
    enabled=True, preparation="natural", source_sha256=raw_sha256,
)
```

Não existe seleção HTTP de V2 nesta entrega. Uma eventual integração deve escolher
explicitamente a versão, preservar V1 para comparação e validar a apresentação
dos escores e do schema; não basta substituir a função atrás de uma URL V1.

## Evidência e limites

A definição matemática de similaridade cosseno é documentada no
[SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.cosine.html).
A associação tolerante de picos é uma adaptação experimental, sem calibração de
probabilidade ou comprovação de validade mineralógica por essa referência.

Orientação e tratamento mudam intensidades. O trabalho de
[Chipera e Bish (2001)](https://clays.org/wp-content/uploads/2020/08/398.pdf)
documenta dependência da montagem e das condições de aquisição. A resposta a
glicolação/aquecimento é evidência adicional, conforme o
[fluxograma USGS](https://pubs.usgs.gov/of/2001/of01-041/htmldocs/flow/d2/d2f5.htm).
Um único CIF de montmorilonita não modela toda a variação basal das esmectitas.
Esta entrega não acrescenta uma regra de expansão nem identifica espécie a partir
de um único pico; preserva os casos não recuperados para avaliação N/G/C posterior.

O ensaio CPAA usa a coluna Fase 1 como referência fornecida pelo usuário, com
autoria de validação ainda não documentada. Melhorou a priorização de esmectitas,
mas houve regressões em outras amostras e sensibilidade ao preparo do upload.
Consequentemente a V2 permanece uma correção preparada para revisão, sem ativação
na homologação ou substituição do classificador. Não usar seu escore como
percentual de mineral, confiança calibrada ou identificação confirmada.
