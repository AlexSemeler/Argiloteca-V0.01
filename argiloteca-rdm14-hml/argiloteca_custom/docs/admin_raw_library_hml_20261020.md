# Acervo administrativo RAW e novos trios — homologação, 20/10/2026

A área administrativa reúne **9.948 arquivos históricos**, com **9.946 curvas anônimas disponíveis**, e permite enviar N/G/C de uma nova amostra para classificação provisória restrita. Os resultados históricos permanecem congelados. A [revisão dos 673 arquivos restritos](restricted_raw_review_hml_20261020.md), em `/administration/drx-review/`, continua somente consulta.

## Uso e acesso

Abrir `/administration/raw-library/` com a permissão administrativa completa nativa do InvenioRDM (`administration_permission`). A navegação reúne revisão restrita, todos os RAWs e **Enviar novo trio** (`#new-trio`). Há textos em português e inglês (`?ln=en`).

- Buscar código/nome anônimo ou mineral e combinar filtros de preparo N/G/C/X, acesso e situação. A listagem apresenta 20 arquivos por página e preserva os filtros.
- Abrir **Ver curva e resultado** para consultar formato, pontos, λ em Å, difratograma, candidatos e arquivos do mesmo grupo. O agrupamento por código não confirma vínculo N/G/C.
- Os dois arquivos históricos vazios continuam visíveis em **Sem curva**, com sua pendência. Entre as curvas verificadas, 9.945 têm eixo 2θ em graus e uma tem coordenada GSAS cuja unidade permanece não confirmada.

**Disponível nas Análises** (`public_snapshot`) descreve presença no snapshot do painel público de Análises. Esse campo não indica publicação de registro no InvenioRDM. **Restrito** inclui os arquivos retidos e todo novo envio. As situações distinguem classificação histórica, recuperado que requer revisão, sem curva e novo resultado provisório.

O gráfico usa Plotly local e uma envoltória min/max, sem deslocamento automático do eixo; o número de pontos originais continua informado. É uma representação reduzida para visualização. A leitura do derivado verifica SHA-256 antes de fornecer os pontos. Não há endpoint de download ou consulta de originais.

## Enviar um novo trio

Selecionar exatamente um `.raw` em cada campo N (natural), G (glicolado) e C (calcinado), declarar que são os preparos correspondentes da mesma amostra e enviar. O servidor exige layouts RAW suportados, até **8 MiB por arquivo**, **10 a 100.000 pontos**, eixo 2θ com todos os valores entre 0 e 180 graus, comprimento de onda declarado e finito e três perfis numéricos distintos. A declaração do usuário é registrada como proveniência; não constitui confirmação mineralógica automática.

A validação e a análise dos três arquivos precedem o commit. Erro mantém a seleção no formulário com JavaScript; o estado ocupado evita envio repetido durante a requisição. No sucesso, a tela abre o código anônimo novo. Uma repetição com os mesmos bytes N/G/C retorna o envio existente, sem duplicar ou substituir entradas.

O resultado automático apresenta candidatos sujeitos a revisão. **Escores não são probabilidades, percentuais de fases ou identificação confirmada**; ausência de candidato não demonstra ausência de argilominerais. O classificador primário usa Cu Kα1 somente dentro da tolerância de precisão do cabeçalho (±0,0001 Å em relação à constante Cu do serviço). Outra radiação não é processada silenciosamente como Cu. O piloto AMCSD/COD V2 considera λ e aparece separado, em modo sombra. O contexto conjunto N/G/C depende de formato RAW1.01, radiação e protocolo suportados; incompatibilidade ou indisponibilidade permanece explícita e não gera conclusão inferida.

As classificações históricas não são recalculadas, mesmo quando uma curva antes ilegível foi recuperada. Sua hipótese de referência Cu e a necessidade de revisar diferenças de radiação são informadas no detalhe. Os novos resultados ficam restritos; não há criação, publicação ou reindexação de registros Invenio nem alteração das classificações públicas.

## Armazenamento e rotas

O índice e os derivados históricos anônimos ficam em `instance_path/app_data/drx-library/`, na montagem somente leitura existente. `ARGILOTECA_ADMIN_RAW_LIBRARY` permite selecionar essa raiz. `index.json` mantém o resumo e os resultados congelados; `reference.json` guarda a referência local utilizada pelo classificador primário dos novos envios.

Novos envios ficam em `instance_path/data/drx-admin-trios/<ARC-código>/`, no volume `uploaded_data` existente; `ARGILOTECA_ADMIN_RAW_UPLOADS` permite selecionar outro diretório privado. Não foi necessária alteração de Docker Compose. Cada envio separa `originals/{N,G,C}.raw`, derivados anônimos em `files/`, `manifest.json`, `analysis.json` e `provenance.private.json`. Este último conserva nomes originais, hashes, ator, data e declaração de preparos. Os bytes originais são preservados; diretórios são privados (0700), arquivos são 0600.

A gravação usa um diretório `.pending-*`, `fsync` dos arquivos e renomeação atômica após completar o conjunto. Um bloqueio `flock` serializa o commit e verifica a impressão digital N/G/C para deduplicar tentativas. Uma falha remove somente o staging novo; o histórico não é sobrescrito.

| Rota | Contrato |
| --- | --- |
| GET `/administration/raw-library/` | Lista histórica e novos envios, filtros e formulário. |
| GET `/administration/raw-library/<id>` | Detalhe; ID anônimo hexadecimal de 24 caracteres. |
| GET `/administration/raw-library/<id>/curve` | JSON de pontos da envoltória e metadados anônimos. |
| POST `/administration/raw-library/trios` | N/G/C e declaração; CSRF da sessão obrigatório. Retorna 201 JSON ou redirecionamento 303 no fluxo HTML. |

As rotas exigem permissão administrativa e respondem com `private, no-store` e `noindex, nofollow`. O blueprint científico valida CSRF nas escritas. Filtro inválido retorna 400; ID/curva ausente, 404; curva inválida ou submissão fora do contrato, 422; requisição acima do limite agregado, 413; acervo indisponível/falha de envio, 503. O detalhe diferencia falta de curva, unidade desconhecida, piloto indisponível e análise inconclusiva.

## Reconstrução e testes

Na raiz do repositório, com a auditoria anterior disponível:

```sh
python3 scripts/build-admin-raw-library.py
```

O construtor usa `output/raw-lifecycle-20261020/restricted/{all-classifications,identity-map}.json`, derivados anônimos do snapshot `lifecycle-v1-20261020`, arquivos anônimos retidos e recuperados de `recovery-v1-20261020`, além da referência local. Copia somente derivados anônimos para `argiloteca-rdm14-hml/app_data/drx-library/files/`, confere hashes e grava índice/referência; não copia originais. As contagens esperadas são fixadas em 9.948/9.946. Para outro levantamento, revisar entradas e contrato antes da reconstrução. Uma divergência em derivado já existente interrompe o build; não usar a reconstrução para sobrescrever arquivos sem investigação.

No ambiente Python instalado da aplicação Invenio, a partir da raiz:

```sh
python -m pytest --noconftest argiloteca-rdm14-hml/argiloteca_custom/tests/test_admin_raw_library.py argiloteca-rdm14-hml/argiloteca_custom/tests/test_restricted_raw_review.py
cp argiloteca-rdm14-hml/argiloteca_custom/tests/test_admin_raw_library.py /tmp/test_admin_raw_library.py
python output/restricted-review-20261020/runtime_library.py
```

O teste nativo exige catálogo histórico disponível e deve rodar em processo isolado. Ele configura armazenamento temporário exclusivo, simula autorização no cliente Flask, mantém a validação nativa de CSRF e reabre o trio gravado para verificar persistência. Não incorporar a identidade de teste à aplicação. Os renders ficam em `/tmp/restricted-review-render/`; `ARGILO_REVIEW_RENDER_ONLY=1` permite atualizar os renders sem submeter o trio temporário.

Evidências em `output/restricted-review-20261020/`:

- `library-tests.log`: **28 testes aprovados**, incluindo validação conjunta, permissão, anonimização, integridade, rollback, persistência, radiação não Cu e deduplicação. Este resultado substitui a contagem inicial de 27 registrada no contrato de superfície.
- `library-regression.log`: **83 testes de regressão aprovados**.
- `library-native-validation.json`: nove renders nativos 200, curva 200, filtro inválido 400, ausência de CSRF 400, POST 201 e três arquivos restritos reabertos apenas em armazenamento temporário; nenhum novo envio no armazenamento de uso.
- `library-corpus-validation.json`: 9.946 curvas conferidas por SHA-256 e parser, dois arquivos sem curva, nenhum recálculo histórico.
- `original-integrity.json` e `preservation.json`: 9.948 originais inalterados e manutenção dos 1.226 registros públicos/1.224 RAWs públicos e das classificações/configuração pública.

As capturas `output/playwright/restricted-review/library/{desktop,mobile,mobile-320,detail-desktop,detail-mobile,detail-320,new-trio-mobile}.png` e os scripts `browser-library-{setup,checks}.js` cobrem formulário e gráfico em 1440, 390 e 320 px. **O navegador recebeu HTML/JSON reais renderizados em cliente de teste com interceptação; não foi validado login de administrador real no navegador.** A autorização e o POST persistido foram verificados separadamente pelo cliente nativo; nenhum envio de teste foi criado no armazenamento de uso.

Na revisão de acabamento inicial, foi solicitado explicitar também no histórico que escore não representa probabilidade ou percentual de fases. O aviso foi acrescentado em PT/EN. O revisor retornou `ship` na verificação dessa correção, julgando o único achado resolvido nos dois idiomas; essa passagem avaliou a correção e não repetiu uma revisão completa da superfície.

Na verificação operacional final, os quatro serviços consultados estavam saudáveis, a raiz privada de novos envios estava gravável e não continha submissões de teste. A preservação dos 1.226 registros públicos, 1.224 RAWs públicos e hashes dos 9.948 originais foi reconfirmada.

## Continuidade visual e manutenção

Comparados `PRODUCT.md`, o contrato `.impeccable/surfaces/ntic-ui-argiloteca-admin-raw-library-html-8679d1a0.md` e os templates/estilos finais, a extensão herda Catamaran/Lato, marrom local `#704025`, detalhes CPAA e SVGs compartilhados, base e navegação administrativas. Reutiliza `restricted-raw-review.css`; seu CSS complementar se limita à biblioteca. Abaixo de 700 px, filtros/tabela rotulada e upload se organizam em uma coluna e o gráfico responde ao tamanho. Não houve redefinição de `DESIGN.md`, `PRODUCT.md`, tokens ou estilos globais; o JavaScript não lê nem escreve as chaves de sessão do comparador público.

Fontes em `argiloteca-rdm14-hml/argiloteca_custom/`: `argiloteca/scientific/{admin_raw_views,admin_raw_store,admin_raw_service}.py`, registro/CSRF em `argiloteca/scientific/views.py`, templates `argiloteca/templates/semantic-ui/argiloteca/admin_raw_{library,detail}.html`, CSS/JS `argiloteca/static/{css,js}/admin-raw-library.*` e testes `tests/test_admin_raw_library.py` e `tests/test_restricted_raw_review.py`. O construtor fica na raiz em `scripts/build-admin-raw-library.py`.

## Validação posterior na sessão real do Firefox

Em 20/10/2026, o envio e a reabertura foram finalmente conferidos na sessão real autenticada do Firefox. Há agora um trio sintético persistido e restrito, **ARC-A087D1A19055845B**, com bloqueio explícito de preparação para publicação. A biblioteca tem 9.951 arquivos, enquanto o acervo público e os 9.948 originais permanecem inalterados. O fluxo curatorial nativo e as novas evidências estão em [admin_raw_curation_hml_20261020.md](admin_raw_curation_hml_20261020.md); as limitações de navegador descritas nas verificações anteriores continuam sendo o registro histórico daquela passagem.
