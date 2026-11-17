# Guia público de DRX — fontes e escopo

Página: `/drx`. Idiomas: português brasileiro (`pt`) e inglês (`en`). Atualização: 20/10/2026.

A página inicial substitui o atalho direto de DRX no menu científico por “Sobre DRX” e o marcador DRX da lista de técnicas por um resumo com acesso ao guia. Os acessos à comparação nas demais páginas são preservados. O guia aponta para `/drx/comparacao`, `/analises/` e o Catálogo de Argilominerais.

## Fontes fornecidas

- `Scopus - Scopus AI.pdf`, título interno “Difratogrametria de Raios X Aplicada a Argilominerais: Princípios, Metodologias e Desafios Atuais”, gerado em 19/10/2026: princípios, preparo, distinção entre identificação e quantificação e limitações. As 41 referências das páginas 7–10 foram preservadas, com numeração e identificadores Scopus. Não foi publicada uma cópia do PDF.
- `EXPLICACAO_PAINEL_DRX_COMPARACAO.md`: fluxo de comparação, preparo inferido pelo nome, curva versus candidatos, picos sobrepostos e limites dos scores.
- `painel_drx_documentacao.md`: Bragg, Cu Kα padrão, etapas e proveniência do processamento, fundamentação e categorias de resultados das regras.
- Templates e rotas atuais do painel: confirmação dos acessos, formatos de exportação e recursos efetivamente disponíveis. Recursos condicionais são descritos como disponíveis conforme os dados e serviços.

O PDF é identificado como síntese de apoio gerada pelo Scopus AI. A lista completa mantém os dados recebidos, inclusive referências a técnicas complementares; isso não equivale a validar independentemente todos os registros bibliográficos.

## Fontes primárias conferidas para leituras iniciais

- Stanjek & Häusler (2004), *Basics of X-ray Diffraction*: página da editora e resumo, DOI https://doi.org/10.1023/B:HYPE.0000032028.60546.38.
- Środoń et al. (2001), *Quantitative X-Ray Diffraction Analysis of Clay-Bearing Rocks From Random Preparations*: página da editora e resumo, DOI https://doi.org/10.1346/CCMN.2001.0490604.
- Poppe et al. (2001), *A Laboratory Manual for X-Ray Powder Diffraction*: metadados oficiais USGS, DOI https://doi.org/10.3133/ofr0141. O diretório histórico do manual retornou HTTP 403 na consulta; usa-se o DOI do registro oficial.

Não se alegou leitura dos textos integrais das publicações com acesso restrito.

## Divergência entre documentos e cautela científica

A explicação anterior apresenta os resultados como hipóteses para curadoria. A documentação técnica atual também define `confirmed_by_rules`, `probable_by_rules` e `possible_by_rules`. O guia explica que “confirmado pelas regras” é um resultado computacional condicionado aos critérios e evidências do protótipo, e não uma validação mineralógica independente.

Score não é teor mineral nem probabilidade calibrada. Normalização não é quantificação. Nome de arquivo não comprova tratamento. Nenhuma tolerância, regra, peso, parser, algoritmo, registro ou arquivo RAW foi alterado para criar a página.

## Verificação

Evidências em `output/playwright/drx-guide/`: renderização nativa das páginas em PT/EN, respostas reais HTTPS, seis combinações de idioma/largura (320, 390 e 1440 px), navegação início → guia → comparação/análises, referências por âncora e teclado, 41 itens bibliográficos, ausência de overflow e fonte de leitura de 16 px.

As prévias Playwright usam HTML renderizado pela aplicação e proxy local GET dos assets/APIs públicos com a CA local. Não encaminham cookies ou credenciais. A navegação de documentos nas prévias usa as respostas HTML registradas; o status das rotas foi conferido separadamente no HTTPS real.

## Links da fundamentação pública (19/10/2026)

A fundamentação passou a listar oito entradas com links: Brindley & Brown (1980), Bailey (1980) como capítulo e Bailey (1988) como volume organizado, Moore & Reynolds (link explicitamente para a 2ª edição de 1997), Drits & Tchoubar (1990), Lanson & Bouchet (1995), Meunier (2005) e o fluxograma USGS (2001). A menção a referências empíricas Pré-Sal UFRGS/Petrobras foi retirada dessa lista a pedido do usuário.

O artigo de Lanson & Bouchet foi identificado também pelo título completo no próprio código e confirmado na bibliografia institucional do autor (ISTerre). Seu PDF e o PDF do fluxograma USGS responderam HTTP 200 e têm cabeçalho PDF válido. Os DOIs de Bailey (1980) e Brindley & Brown redirecionam ao GeoScienceWorld, que bloqueou o cliente automatizado com HTTP 403; o vínculo DOI e o destino editorial foram preservados. Oxford e De Gruyter retornaram desafios de navegador (HTTP 202). O registro CiNii da edição de Moore & Reynolds respondeu HTTP 200 e está disponível como acesso bibliográfico alternativo. Não se alegou acesso livre aos textos integrais de todas as obras. Evidências em `output/playwright/drx-foundation/`.


## Metodologia revisada em 20/10/2026

A seção `#metodologia` em `/drx` passou a documentar o estado implementado:

- inventário público de derivados anônimos, distinto da biblioteca RAW restrita;
- leitura por assinatura/layout, eixo declarado no fluxo administrativo RAW1.01 e proveniência de correções no painel público;
- seleção/comparação e temporários preservados ao alternar internamente Análises/DRX, modo expandido persistente e confirmação em Remover todas;
- classificador primário, piloto público V1 e V2/contexto N/G/C administrativo apresentados separadamente, em modo sombra;
- COD, recorte COD Inorganics e AMCSD com links e distinção entre bases completas, pacotes Match! e índice nativo limitado de 12 estruturas/10 minerais;
- contexto experimental para famílias clorita/esmectita, limites da comparação CPAA/Fase 1 e ausência de validação cega;
- visualização e arquivo final administrativo N/G/C, relatório local HTML/JSON/CSV, rascunho nativo com três derivados e metadados pendentes sem publicação automática;
- disponibilidade real de exemplos nas páginas minerais e estado não presumido da conexão RAG.

A frase sobre download foi corrigida: o inventário público fornece cópias anônimas, não os originais restritos. A descrição antiga de “confirmado pelas regras” foi substituída pela distinção entre compatibilidade de família, resultado inconclusivo e validação independente. As referências bibliográficas existentes foram mantidas, sem menção ao PDF de apoio na interface.

Fontes oficiais consultadas nesta revisão:

- COD: https://www.crystallography.net/cod/ — escopo e reconhecimento dos autores dos dados estruturais.
- Crystal Impact: https://www.crystalimpact.com/match/download.htm — pacotes COD, COD inorganic compounds only e Minerals (AMCSD) only. A existência desses pacotes não significa que foram integralmente importados na Argiloteca.
- Downs & Hall-Wallace (2003): https://www.geo.arizona.edu/xtal/group/pdf/am88_247.pdf — documentação primária AMCSD. O portal `rruff.geo.arizona.edu/AMS/amcsd.php` excedeu o tempo de consulta automatizada; não foi alegada indisponibilidade universal. O link fornecido foi mantido e o artigo disponibilizado como alternativa.
- Gražulis et al. (2009): https://journals.iucr.org/j/issues/2009/04/00/kk5039/ — publicação sobre COD.

O conteúdo foi confrontado com `reference_pilot_v1.json`, serviços V1/V2/contexto NGC, sessão científica, templates e fluxo administrativo atuais. Nenhuma regra, escore ou classificação foi alterada por esta revisão editorial.
