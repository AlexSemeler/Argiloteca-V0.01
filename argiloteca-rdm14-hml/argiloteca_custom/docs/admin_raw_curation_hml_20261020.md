# Teste no Firefox e preparação curatorial de trios — 20/10/2026

> Revisão posterior no mesmo dia: a preparação passou a aceitar autoria, data e licença pendentes, sem atribuí-las automaticamente. O teste real com um trio do CPAA e o relatório N/G/C estão documentados em [Visualização e arquivo final N/G/C](admin_ngc_final_report_hml_20261020.md). As exigências de metadados completas descritas abaixo representam a versão anterior do formulário; a publicação não foi executada em nenhuma das versões.

## Resultado comprovado

Na sessão administrativa real do Firefox, foram selecionados pelo seletor nativo os três arquivos sintéticos `TESTE_FIREFOX_N.raw`, `TESTE_FIREFOX_G.raw` e `TESTE_FIREFOX_C.raw`. O envio gerou **ARC-A087D1A19055845B**, com três curvas de 1.486 pontos, λ=1,54060 Å, acesso restrito e resultados provisórios em modo sombra. Os preparos N/G/C foram reabertos individualmente e o envio reapareceu após reiniciar o serviço web. Os hashes dos três originais preservados coincidem com os das fixtures; os derivados também conferem com o manifesto. Resultados automáticos desse ensaio não são validação mineralógica.

O Firefox exibiu o bloqueio na seção **Publicação de trio curado** e no modo responsivo de 320 × 844 px. O cabeçalho, resultados em lista e links do trio se ajustaram à largura. A simulação de viewport não equivale a teste em aparelho físico. A sessão do Firefox foi restaurada ao modo de computador.

O teste deixou somente três arquivos novos na biblioteca administrativa: **9.951 arquivos / 9.949 curvas**, incluindo os dois arquivos históricos vazios. O acervo público permaneceu com **1.226 registros / 1.224 RAWs**. Os **9.948 originais** mantêm os SHA-256 anteriores. Classificadores, recuperação, snapshots e configuração de publicação existentes não foram alterados.

## Como publicar um trio curado

1. Em **Administração → Arquivos RAW e classificações**, localize a amostra e abra **Ver curva e resultado**.
2. Consulte as três curvas e os vínculos. Na seção **Publicação de trio curado**, somente grupos elegíveis exibem o formulário.
3. Informe título, autoria responsável, data, licença autorizada e contexto. Confirme curadoria dos vínculos, anonimato e direitos.
4. Acione **Preparar rascunho para publicação**. A ação cria um rascunho nativo privado, anexa exclusivamente as três cópias anônimas e abre `/uploads/<id>`.
5. Complete os metadados e confira o acesso antes de publicar pelo formulário nativo do Invenio. **Este trabalho não executou essa publicação.** O fluxo utiliza a validação de bytes RAW já instalada no serviço nativo.

Originais, correspondência de identidade e escores automáticos não são anexados ao rascunho. A autoria e a licença exigem preenchimento explícito; a conta administrativa não é automaticamente atribuída como autora científica. O conjunto utiliza metadados nativos de dataset; o formulário científico completo continua disponível no fluxo existente, sem preencher campos científicos não confirmados. Não há reclassificação de arquivos anteriores nem atualização automática dos snapshots estáticos a partir da preparação de rascunhos.

A biblioteca administrativa guarda fontes e resultados restritos mesmo após eventual publicação das cópias no Invenio. O vínculo consulta o estado nativo para oferecer o registro publicado, o rascunho ou uma pendência explícita, sem reescrever as classificações.

## Bloqueios e integridade

- Permissão administrativa nativa e CSRF também no POST; respostas administrativas `private, no-store` e `noindex`.
- Exigidos exatamente três arquivos do mesmo código, com N/G/C distintos, curvas disponíveis e hashes íntegros.
- O contrato de publicação verifica RAW1.01 comprovado, aquisição concluída, cabeçalho anônimo, comprimento de onda e perfis numéricos distintos. Formatos recuperados e pendências não recebem liberação por uma simples confirmação visual.
- Grupos já disponíveis no inventário público são bloqueados para evitar duplicação. Revisar seu registro existente.
- `test_only` bloqueia a preparação, inclusive em POST direto. O marcador binário `ARGILOTECA_SYNTHETIC_TEST_V1` identifica as fixtures mesmo sem marcar a opção no formulário.
- Novos envios RAW1.01 usam o mesmo anonimizador canônico da validação de publicação. Originais, intensidades e eixo são preservados. Outros layouts recuperáveis continuam sujeitos à revisão.
- A identidade do chamador é repassada ao serviço nativo. Nenhum uso de identidade de sistema ou chamada de publicação no adaptador.
- Transferência transacional com três arquivos `completed`, tamanho e checksum conferidos antes de confirmar o rascunho.
- Vínculo privado e bloqueio de concorrência em `data/drx-admin-curation/`, no volume existente. Repetir a ação não cria outro rascunho. Um checkpoint é escrito antes do commit para impedir duplicação após interrupção.
- Se o commit falhar depois do checkpoint, ou o rascunho for excluído, o vínculo permanece bloqueado para revisão administrativa. Não remover o checkpoint antes de conferir no banco o destino do rascunho; o código não recria automaticamente um depósito inacessível.

## Verificações e limites

**45 testes aprovados**: envio, persistência, preservação, validação conjunta, perfis repetidos, corrupção, falhas de transferência, autorização, deduplicação, metadados, confirmações, bloqueio sintético e estados nativos de publicação/exclusão. As publicações nesses testes de estado são simulações unitárias; nenhuma publicação foi executada.

O cliente Flask com serviços e templates reais confirmou: acesso anônimo 403; CSRF ausente 400; metadados incompletos 422; POST direto para o trio sintético 422; formulário elegível em PT/EN 200. Os envios desse cliente usam armazenamento temporário exclusivo. A sessão real do Firefox foi usada separadamente para o envio persistido descrito acima.

No serviço real do Invenio, um ensaio isolado exerceu criação e transferência dos três anexos com a identidade administrativa, sem erros de validação. A transação foi revertida e a inexistência do rascunho foi conferida depois do rollback. Isso valida preparação e transferência, não publicação, indexação ou coleta OAI de um novo registro.

O formulário elegível foi inspecionado em Chromium isolado com HTML real renderizado pelo Invenio e interceptação explícita de preview, em **1440/390/320 px, PT/EN**. Essa passagem valida layout, fonte Catamaran e botão marrom; não é evidência de autenticação ou publicação no Chromium. A curva dessa prévia foi deliberadamente indisponibilizada. Não houve POST no preview. O espaço inferior foi ajustado para o assistente flutuante não cobrir a ação final no celular.

Evidências locais: `output/admin-curation-20261020/{tests.log,routes.log,native-draft-check.log,preservation.json,original-integrity.json,synthetic-fixture.json,layout-check.log}`. Capturas e roteiros visuais: `output/playwright/admin-curation-20261020/` (excluído do versionamento). Esses renders contêm tokens de cliente de teste e devem permanecer locais.

## Implementação

- `scientific/admin_raw_curation.py`: elegibilidade, metadados nativos, vínculo e transferência de rascunhos.
- `scientific/admin_raw_views.py`: GET e POST administrativos; novo endpoint `/administration/raw-library/<item_id>/prepare-draft`.
- `scientific/admin_raw_service.py`: identificação de ensaios e derivação canônica para novos RAW1.01.
- Template `_admin_raw_curation.html`, inclusão em `admin_raw_detail.html` e ajustes locais de CSS/JS.
- Testes `test_admin_raw_curation.py` e adições em `test_admin_raw_library.py`.

Ativação: reinício apenas de `web-ui`, com os módulos/templates/estilos já montados. Não foi necessário migrar banco, alterar Docker Compose, publicar registros ou modificar os 14 schemas científicos.
