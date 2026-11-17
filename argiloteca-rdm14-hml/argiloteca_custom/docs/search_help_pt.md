# Ajuda de pesquisa bilíngue PT/EN

A versão atual foi ampliada e validada primeiro na instância local e depois publicada em produção em **02/11/2026**. O inglês apresenta o mesmo conteúdo e os mesmos exemplos do português. A primeira entrega, apenas em português, permanece registrada abaixo como histórico.

- Local: [Português](https://127.0.0.1:5101/help/search?ln=pt) e [English](https://127.0.0.1:5101/help/search?ln=en).
- Produção: [Português](https://vmx000080.nuvem.ufrgs.br/help/search?ln=pt) e [English](https://vmx000080.nuvem.ufrgs.br/help/search?ln=en).

Os overrides `templates/semantic-ui/invenio_app_rdm/help/search.pt.html` e `search.en.html` usam o mecanismo nativo do InvenioRDM: a rota escolhe `search.<locale>.html`, com fallback inglês. A preferência do seletor PT/EN é mantida ao abrir a URL sem `ln`, e os exemplos e o link final levam à busca com o idioma correspondente. Não foi necessário modificar dependências nem compilar catálogos globais.

O guia contém os mesmos 26 exemplos clicáveis próprios do acervo nos dois idiomas, distribuídos em 11 seções h2 e quatro subseções h3: caulinita/kaolinite, esmectita/smectite, halloysite, difração de raios X (DRX/XRD), campos de título/descrição/assuntos, conjuntos de dados, intervalos de datas, prefixo DOI Mendeley Data, ausência de valores, peso por campo, grafia aproximada, proximidade e curingas. As explicações e a navegação são localizadas; consultas, nomes de campos, identificadores, datas e operadores AND/OR/NOT/TO mantêm a sintaxe original. O inglês conserva os nomes portugueses nos exemplos e explica seus equivalentes. Nenhum título, resumo ou arquivo do acervo foi traduzido ou alterado.

Ambos os artigos usam o contêiner normal do site, atendendo à preferência expressa por páginas mais largas: em uma janela de 1440 px, a largura passou de 700 para 1238 px; em 390 px, mede 358 px. O estilo compartilhado `argiloteca/static/css/search-help.css` mantém o espaçamento final do artigo e a quebra de consultas longas em telas estreitas. Somente nas páginas desta ajuda, o lançador existente do assistente fica no fluxo após o rodapé para liberar a leitura do artigo. Catamaran, Lato, cores, marcas, componentes Semantic UI e o shell público existentes foram preservados.

## Validação local da versão bilíngue

Os 26 exemplos retornaram HTTP 200 na API pública local. A verificação registrou paridade das consultas, das 11 seções e das quatro subseções, correspondência entre texto e consulta dos links, idioma dos links, cookie PT/EN e abertura de um exemplo inglês nos resultados. As quatro páginas PT/EN em desktop/celular retornaram HTTP 200, com o lançador em posição estática, sem erros JavaScript ou transbordamento documental nos estados verificados. Contagens de resultados não são fixadas no guia: dependem do acervo e dos filtros.

A revisão independente local teve disposição `ship`, sem correções materiais. Os SHA256 dos dois templates, da folha de estilos e das quatro capturas correspondem a `.impeccable/review/search-help-bilingual/manifest.json`; os fontes permanecem iguais aos revisados. As capturas completas têm dimensões de 1440×3555 (PT) e 1440×3532 (EN) no desktop; 390×6303 (PT) e 390×5963 (EN) no celular. O detector foi executado uma vez, com resultado `[]`, e informou limitação na resolução da folha de estilos ligada por Jinja; a folha CSS também foi fornecida diretamente. Esta evidência não constitui certificação integral de acessibilidade, contraste ou tecnologia assistiva. A documentação reutiliza os resultados existentes, sem nova execução de navegador, testes ou detector.

Evidências locais atuais: `.impeccable/surfaces/search-help-bilingual.md`, `.impeccable/review/search-help-bilingual/{review-packet,finish-review}.md`, `manifest.json`, quatro capturas e `output/search-help-bilingual-20261102/local-verification.json`. A extensão preserva a identidade existente; não cria `DESIGN.md` nem `.impeccable/design.json`.

## Implantação e verificação da versão bilíngue em produção

O recibo `output/search-help-bilingual-20261102/production-deployment.json` confirma a implantação da imagem `argiloteca-rdm14-prod:14.0.4-20261102-search-help-bilingual`, baseada na primeira entrega `14.0.4-20261102-search-help`. Somente `web-ui` foi atualizado, com três arquivos instalados: os dois overrides e a folha de estilos compartilhada. O recibo registra a preservação de 19 tabelas nativas, 2.476 assets compilados e do arquivo inglês do fornecedor; o override inglês personaliza a página renderizada. Não houve migração do banco, nem cópia, importação ou exclusão de registros, jobs ou arquivos científicos.

`production-verification.json` registra os mesmos 26 exemplos com HTTP 200, paridade PT/EN das consultas e seções, cookie de idioma persistente, navegação de exemplo inglês, nenhum erro JavaScript e larguras de 1238 px no desktop e 358 px no celular para ambos os idiomas, sem transbordamento documental nos estados verificados. As quatro capturas de `output/search-help-bilingual-20261102/production/` foram abertas e inspecionadas pelo responsável pela implantação; seus hashes correspondem a `final-verification.json` e às capturas locais revisadas. A revisão independente documentada é a local; a confirmação de produção está nos recibos, resultados e capturas posteriores.

## Histórico: primeira entrega apenas em português

A tradução portuguesa inicial foi criada e validada localmente e publicada em produção em **02/11/2026**, antes da extensão bilíngue. Naquela entrega, a ajuda inglesa original permaneceu intacta e o artigo ainda usava o contêiner de texto estreito. Os dados de implantação a seguir descrevem essa primeira entrega, não a publicação bilíngue subsequente.

Em cada ambiente, os 26 exemplos retornaram HTTP 200 na API pública. Foram conferidas as equivalências entre busca simples/OR, AND/+ e NOT/-, a correspondência exata entre texto e consulta dos links, a abertura de resultados e o seletor nativo de idioma com cookie. As quatro capturas em larguras 1440/390 px foram inspecionadas; sem erros JavaScript ou transbordamento documental nos estados verificados. Contagens de resultados não foram fixadas no guia: dependem do acervo e dos filtros.

Somente `web-ui` recebeu a imagem `argiloteca-rdm14-prod:14.0.4-20261102-search-help`, baseada em `14.0.4-20261101-administration`. Foram conferidos os hashes dos dois arquivos instalados e a preservação da ajuda inglesa, de 19 tabelas nativas e de 2.476 assets compilados. Não houve migração, importação, publicação ou exclusão de registros. A composição anterior está preservada no diretório privado `/home/vmx000080/argiloteca-search-help-20261102/backup/` para reversão de código; não é necessária restauração do banco para remover esta tradução.

A composição dessa entrega usou `/home/vmx000080/argiloteca-rdm14-production/runtime/compose.yml`. A atualização de conteúdo não substituiu a implantação administrativa de 01/11: API, workers e coletores mantiveram suas versões anteriores.

Evidências locais: `output/search-help-pt-20261102/`, incluindo `local-verification.json`, `production-verification.json`, `production-deployment.json`, `verification-summary.json` e capturas. A publicação continuou em segundo plano após uma queda da sessão SSH; o recibo foi recuperado após reconexão. A primeira tentativa de API pelo cliente Node encontrou a CA privada; a validação final usou a conexão do navegador com chave pública fixada, sem desabilitar globalmente a verificação HTTPS.
