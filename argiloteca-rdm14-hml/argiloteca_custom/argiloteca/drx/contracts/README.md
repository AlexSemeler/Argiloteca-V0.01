# Contratos DRX v1

Estes contratos formam uma fronteira independente de Flask/Invenio para a
modularização incremental do painel. Todos os payloads usam
`schema_version: "1.0"`; os identificadores Python `*.v1` nomeiam o tipo do
contrato, mas ainda não substituem os schemas legados de `drx_core`.

## Unidades e estados

- ângulo: `two_theta_deg`, em graus 2θ;
- espaçamento: `d_spacing_angstrom`, em Å;
- largura: `fwhm`, em graus 2θ, salvo indicação explícita do método;
- intensidade: valor numérico na escala da curva;
- estados: `calculated`, `inferred`, `reviewed`, `confirmed` e `inconclusive`;
- preparações: `natural`, `glicolada`, `calcinada` e `indeterminada`.

Um `MineralCandidate` sem estado explícito é sempre `inferred`. Confirmação
exige entrada explícita de uma etapa de curadoria; os validadores não promovem
hipóteses automaticamente.

## Compatibilidade

Nesta primeira etapa os contratos são aditivos. Nenhuma rota ou resposta
pública existente foi modificada. Adaptadores para `/api/v1/drx` serão criados
em uma etapa posterior e deverão manter `/argiloteca/drx/*` e
`/api/argiloteca/drx/*` durante a janela de compatibilidade.
