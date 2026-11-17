# Visualização e arquivo final N/G/C — homologação, 20/10/2026

## Fluxo disponível

Após enviar um trio pela biblioteca RAW administrativa, o navegador abre o detalhe N com a seção **Visão conjunta N/G/C e minerais candidatos**. A seção mostra as três curvas, as evidências conjuntas salvas e os candidatos individuais. Não executa uma nova classificação nem altera resultados históricos. Grupos sem análise conjunta salva não recebem resultados inventados.

O botão **Baixar arquivo final N/G/C (ZIP)** reúne:

- `relatorio-ngc.html`: gráfico interativo e evidências, com Plotly e fonte Catamaran incorporados. Pode ser aberto localmente; Imprimir permite salvar PDF.
- `resultados-ngc.json`: resumo dos resultados e proveniência, sem os nomes originais.
- `curvas-ngc.csv`: todos os pontos e intensidades originais dos derivados anônimos.
- `LEIA-ME.txt`, `LICENCAS.txt` e `SHA256SUMS.txt`.

O pacote não inclui os RAWs originais nem a correspondência de identidade. Não é anexado automaticamente ao depósito: o rascunho nativo contém exclusivamente os três RAWs anônimos. A transferência do relatório pelo botão é uma exportação explícita do administrador.

## Teste real no Firefox

Por autorização do usuário, foi escolhido no RAR do CPAA o trio completo 106183, após confirmar que RC-03, RC-04 e RC-05 constavam apenas na planilha. O envio pelo seletor nativo gerou **ARC-EF77FA2A95A9CD43**, com N/G/C de 1.486 pontos cada e λ=1,54060 Å.

O botão **Preparar rascunho para publicação** criou **aw025-95123**. O formulário nativo foi recarregado e reaberto pelo vínculo administrativo. Os três arquivos anônimos, o título e a descrição permaneceram. A verificação independente dos bytes anexados confirmou SHA-256 igual aos derivados e aprovação pela validação de anonimização RAW. Autoria, data e licença permaneceram pendentes; nenhuma pessoa ou licença foi atribuída automaticamente. Não foi acionada a publicação.

No Firefox, foram conferidos o gráfico no computador, os controles e as evidências em viewport de **320 × 844 px**, a abertura do relatório em aba independente e o download concluído do ZIP. O HTML extraído também foi aberto por URL `file:` no Firefox e renderizou as três curvas. A simulação de viewport não substitui teste em aparelho físico. O navegador foi restaurado ao modo de computador.

Neste trio, o contexto salvo indicou **compatibilidade com o grupo das esmectitas, sujeita a revisão**, com d N=15,225 Å, G=16,916 Å e C=9,543 Å; a reflexão companheira em G foi 8,434 Å. Clorita permaneceu inconclusiva. Isso não confirma espécie ou proporção mineralógica. Escores individuais e evidências AMCSD/COD são apresentados separadamente, sem votação ou combinação de probabilidades. As regras conjuntas exibidas cobrem cloritas e esmectitas; o relatório explicita os limites do protótipo.

## Contratos e verificações

Rotas novas, somente leitura e com permissão administrativa nativa:

- `GET /administration/raw-library/<item_id>/ngc`: JSON com as três curvas para visualização.
- `GET /administration/raw-library/<item_id>/ngc/report?format=html|json|zip`: relatório ou exportação.

Respostas privadas, `no-store` e `noindex`. Acesso anônimo retorna 403; grupo indisponível, hash divergente ou proveniência incompatível não produz relatório. A exportação verifica os derivados novamente. O gráfico normaliza pelo máximo absoluto apenas na apresentação; o CSV preserva todos os valores.

**54 testes aprovados**, cobrindo biblioteca, curadoria, exportação e revisão restrita. O cliente Flask real confirmou PT/EN, três curvas, ZIP e 4.458 pontos em CSV, sem publicações ou novos envios persistentes no ensaio isolado. Os testes não modificam pesos, limiares ou classificadores científicos.

A verificação final confirmou os **9.948 originais** com os mesmos SHA-256, classificadores/recuperação/snapshots/configuração preservados e acervo público ainda com **1.226 registros / 1.224 RAWs**. Sem autenticação, o registro publicado do novo ID retorna 404; o rascunho, seu conteúdo e o ZIP administrativo retornam 403. Os únicos novos dados persistentes deste teste são o trio administrativo restrito e o rascunho não publicado.

Evidências locais restritas em `output/ngc-final-report-20261020/`: `tests.log`, `report-routes.log`, `live-draft.json`, `archive-check.json`, `original-integrity.json`, `anonymous-access.json`, `preservation.json` e o ZIP baixado no Firefox. O diretório é excluído do versionamento.

## Metadados pendentes no rascunho

Esta revisão permite preparar um **rascunho incompleto**, exigindo título, confirmação do vínculo N/G/C e anonimato. Autoria, data e licença são opcionais nessa etapa. Valores informados são validados; escolher uma licença exige confirmar os direitos. A API nativa pode apontar apenas os erros esperados de autoria/data ausentes nessa preparação; outros erros continuam bloqueando a transferência. As pendências ficam registradas no vínculo privado e devem ser resolvidas no editor nativo antes de eventual publicação. A identidade administrativa não é tratada como autoria científica.

O fluxo não contém chamada de publicação. Os bloqueios para trios sintéticos, formatos não elegíveis, aquisição incompleta, perfis repetidos e grupos já públicos continuam ativos.
