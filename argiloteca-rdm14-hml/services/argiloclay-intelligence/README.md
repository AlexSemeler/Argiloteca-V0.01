# ARGILOCLAY: piloto local de inteligência documental

**Estado atual — 22/10/2026:** a inteligência está implantada em https://vmx000080.nuvem.ufrgs.br/argiloclay com Qwen 0.6B, RAG/MCP, geração assíncrona de até 40 segundos e fallback citado. O corpus DRX foi preservado. As respostas de classificação e apresentação de registros estão mais didáticas, com contexto do launcher corrigido. Consulte o [relatório atual, perguntas reais e rollback](../../../output/argiloclay-didactic-20261022/README.md).

As seções abaixo registram a preparação inicial de 21/10/2026. Contagens de homologação, modelos experimentais e pendências mencionadas nesse histórico não descrevem o estado atual de produção; use o relatório acima para a configuração ativa.

## O que está pronto

- Ingestão de 81 termos de argilominerais, 12 grupos e uma visão geral derivada desses vocabulários.
- Extração dos 61 PDFs autorizados, 67 páginas, em 240 trechos com página, arquivo e SHA-256.
- Snapshot de 1.307 registros públicos da API **local de homologação**, em 10.724 trechos. Isso não é uma contagem confirmada da produção remota.
- Índice SQLite FTS5 com BM25, aliases PT/EN, filtros e 11.058 trechos no total. Não há busca vetorial nesta versão.
- API compatível com o `RagClient` existente: `/api/v1/drx/status` e `/api/v1/drx/query`.
- MCP stdio com `search_evidence`, `lookup_vocabulary`, `get_public_record`, `get_section_guide` e `corpus_status`, somente de leitura.
- Qwen3 1.7B Q4_K_M baixado em `.models/`, com verificação SHA-256 de todos os componentes. Perfil local `argiloclay-evidence:1.7b` criado por Modelfile. **Configuração de prompt não é fine-tuning.**
- Receita LoRA e 465 exemplos comportamentais iniciais: 275 treino, 105 validação, 85 teste, separados por família. São sementes sintéticas para revisão; nenhum adaptador foi treinado.

Os pesos e os snapshots ficam fora do Git. O código remoto anterior foi copiado para `output/argiloclay-intelligence-20261021/remote-source/` na raiz desta homologação, sem ambiente virtual, credenciais ou índices. O novo piloto tem namespace próprio e não substitui o código remoto.

## Escolha para o servidor

A inspeção SSH encontrou Ubuntu x86_64, **12 vCPUs AMD Opteron 6136, sem AVX/AVX2**, 15.978 MiB de RAM e aproximadamente 11 GB livres em disco. Havia cerca de 12.175 MiB de memória disponível na leitura. Não foi confirmado acelerador GPU.

O Ollama remoto 0.40.3 já tem `qwen3:1.7b`, `qwen3:0.6b` e `qwen2.5:0.5b`. O serviço RAG ativo em 7860 usa resposta extrativa e 9.418 documentos: 8.954 entradas DRX mais 464 fontes de conhecimento. Seus limites atuais são 512 MiB e uma CPU; não comportam carregar LLM dentro do processo web.

O teste curto de Qwen3 1.7B desta sessão expirou em 55 segundos. Sete respostas históricas de 14/10/2026 mediram 1,11–1,22 tokens/s de saída e 87,50–266,93 segundos totais. Por isso a recomendação é:

1. Produção imediata: recuperação e respostas extrativas, sem espera por LLM.
2. Desenvolvimento local: Qwen3 1.7B Q4_K_M, `think=false`, contexto 2.048, quatro threads, saída até 96 tokens, concorrência um. O teste no Mac M4 Pro levou cerca de 1,27 s; esse resultado não descreve o servidor.
3. Síntese remota opcional: tarefa em segundo plano, separada do Gunicorn, após medir latência e fidelidade. Não aumentar o timeout do Invenio para vários minutos.
4. Não escolher 4B ou 7B só porque cabem na RAM. Neste servidor a velocidade da CPU é o impedimento principal. Não é necessário baixar outro modelo grande para comprovar isso.

O perfil Qwen3 usa a mesma camada de pesos do modelo remoto, SHA-256 `3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6`. A etiqueta comercial é 1.7B; o Ollama informa cerca de 2,0B parâmetros. A licença base é Apache-2.0, conforme [Qwen](https://huggingface.co/Qwen/Qwen3-1.7B) e [Ollama](https://ollama.com/library/qwen3:1.7b).

## Execução local

Execute a partir desta pasta. O ambiente `.venv` e os pesos já foram criados nesta sessão. Para reconstruir as dependências na mesma plataforma:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Em um terminal, use o armazenamento de modelos isolado:

```bash
export OLLAMA_HOST=127.0.0.1:11435
export OLLAMA_MODELS="$PWD/.models"
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
ollama serve
```

Em outro terminal, caso seja necessário recriar o perfil:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3:1.7b
OLLAMA_HOST=127.0.0.1:11435 ollama create argiloclay-evidence:1.7b -f Modelfile
```

Para servir o corpus já preparado, com resposta extrativa:

```bash
.venv/bin/gunicorn --bind 127.0.0.1:7861 --workers 1 --threads 2 --timeout 10 argiloclay_intelligence.api:app
```

Para experimentar a seleção de evidências pelo modelo, inicie outra instância com `ARGILOCLAY_USE_MODEL=1`, `ARGILOCLAY_MODEL=argiloclay-evidence:1.7b` e `ARGILOCLAY_OLLAMA_URL=http://127.0.0.1:11435`. O limite padrão de espera é quatro segundos; o timeout conserva a resposta extrativa. Essa opção não produz prosa livre.

```bash
curl http://127.0.0.1:7861/api/v1/drx/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"O que é caulinita?","filters":{},"top_k":3}'
```

Para disponibilizar as ferramentas MCP em um host local, configure o executável absoluto `.venv/bin/python`, argumentos `-m argiloclay_intelligence.mcp_server`, esta pasta como diretório de trabalho e `ARGILOCLAY_INDEX` absoluto. O transporte é stdio, sem porta pública. `get_public_record` lê o snapshot público quando não há origem configurada; o gateway Invenio verifica novamente a visibilidade e a atualização antes de mostrar a fonte. Com uma origem HTTPS fixa em `ARGILOCLAY_INVENIO_URL` e certificado confiável, pode ler a API pública; essa opção ainda não foi testada na API remota. O modo conectado local usa o snapshot e a revalidação pelo serviço nativo do Invenio.

## Atualização do corpus

```bash
.venv/bin/python -m argiloclay_intelligence.snapshot \
  --base-url https://127.0.0.1:5101 --local-self-signed
.venv/bin/python -m argiloclay_intelligence.corpus \
  --pdf-zip /Users/alexandresemeler/argilas/povoamento/handbook/pdfs.zip \
  --records storage/records.jsonl \
  --rights-note 'Autorização do usuário para RAG e fine-tuning confirmada em 21/10/2026'
```

A exceção de certificado se aplica exclusivamente ao snapshot no loopback local. Para produção use HTTPS validado. Apenas `GET /api/records` é permitido. Não há token administrativo, acesso PostgreSQL/OpenSearch, leitura de drafts, download de arquivos ou escrita em registros. A indexação é uma operação administrativa fora das ferramentas MCP e substitui o índice local atomicamente. Exclusões e alterações na API só aparecerão depois de atualizar o snapshot; a integração futura deve revalidar a visibilidade antes de mostrar uma fonte.

## Respostas vinculadas às fontes

No modo estrito, a saída contém trechos originais; o modelo opcional só escolhe seus IDs. O backend rejeita citações inexistentes, prosa livre, JSON inválido e geração incompleta. Uma seleção válida publica exatamente os trechos compactados enviados ao modelo. Sem resultado, retorna “Não conclusivo: não há evidência suficiente na Argiloteca para responder.”

Isso impede que a prosa inventada pelo modelo seja exibida. **Não prova que todo trecho recuperado responda semanticamente à pergunta**: recuperação lexical ainda pode trazer menções incidentais, e uma fonte pode conter erro. Os trechos devem ser renderizados como texto, sem executar HTML, links ou instruções neles presentes. O piloto não tem permissão para identificar minerais, recalcular DRX, editar ou publicar registros.

O conteúdo enviado ao modelo é limitado a três trechos de até 220 bytes cada, pergunta até 200 bytes e instrução curta. O limite de texto é 1.650 bytes, com reserva para template e 96 tokens de saída em contexto de 2.048. O restante da evidência e a proveniência continuam na API. Não enviar todo o histórico de conversa.

## Qualidade científica e limites encontrados

- Alguns PDFs apresentam extração defeituosa de fórmulas, gregos, sinais e tabelas. A página de caulinita foi renderizada e inspecionada; isso não valida as outras 66 páginas. Todos os PDFs conservam `numeric_validation=pending_visual_review`. Não utilizar seus números como medidas validadas de amostras.
- Seis valores de `family` não têm entrada exata em `grupo_mineralogico`: `chlorite_related`, `mica_group`, `phyllosilicate_related`, `pyrophyllite_talc_related`, `smectite_related`, `vermiculite_related`. Não foram corrigidos nem fundidos automaticamente.
- O vocabulário apresenta grupos, espécies, interestratificados e materiais; não tratar seus 81 termos como 81 espécies. “Ilita”, por exemplo, conserva a categoria declarada pelo vocabulário.
- A visão geral “argilominerais na Argiloteca” descreve os vocabulários fornecidos. Não substitui uma definição mineralógica geral revisada. Faltam fichas conceituais didáticas em PT-BR e avaliação por especialista para oferecer explicações completas e uniformes de todas as famílias.
- Dados numéricos de fichas minerais de referência não são análises químicas ou medidas DRX de amostras do Invenio. A hierarquia do handbook pode diferir da do vocabulário; preservar e explicitar essa divergência.
- Filtros `sample_code`, `sample_base` e `preparation` sem mapeamento comprovado não são descartados: retornam ausência de evidência. Não há suporte integrado às curvas temporárias ou ao contexto da seleção N/G/C nesta versão.

## Fine-tuning e agentes

RAG mantém os fatos atualizados; MCP expõe capacidades autorizadas; fine-tuning pode melhorar seleção de evidências, formato e recusa. Nenhum deles garante ausência absoluta de erro. Fine-tuning não deve memorizar o banco nem substituir controle de acesso e validação da resposta.

`training/prepare.py` gera sementes comportamentais com positivos, distratores, perguntas externas, falta de dados e injeção. Os splits ficam separados por família. Os PDFs foram autorizados, mas seus trechos ainda não foram transformados em exemplos científicos de treino devido à revisão numérica e de extração pendente. Os exemplos atuais não qualificam um especialista mineralógico.

`training/train_lora.py` é uma receita **não executada** para GPU CUDA local, LoRA r=8, duas épocas e contexto 2.048, com loss somente sobre a resposta do assistente. Crie outro ambiente com `training/requirements.txt`, revise os dados e execute com `--reviewed-data DIRETORIO`. O código recusa treino na VM sem CUDA. Não usa serviços pagos. Após o treino: avaliação independente, comparação com a base, mesclagem, conversão GGUF, quantização Q4_K_M e novo benchmark antes de promoção. Não chamar o Modelfile de treinamento.

Agentes podem ser funções de um workflow: normalizador de vocabulário, recuperador, leitor de registros e verificador de citações. No servidor, execute-os sequencialmente, com um único modelo e até duas chamadas de ferramenta por consulta. A seleção de ferramentas pode ser determinística; não é necessário um framework multiagente. Não permitir navegação livre, shell, SQL arbitrário, autoalteração de regras, aprendizado automático com usuários ou escrita no acervo. Curadoria, ingestão e geração de datasets são tarefas administrativas fora do caminho da resposta.

## Validação executada

14 testes unitários passaram. A bateria manual de recuperação passou em 18/18 casos, com hit@4 de 100% nos dez positivos e recusa em oito negativos/filtros sem correspondência. Mediana local aproximada de 9 ms. Esse conjunto pequeno foi usado durante o desenvolvimento e **não é validação científica independente nem estimativa de precisão em produção**.

Foi exercitado o MCP real por stdio: inicialização, listagem das quatro ferramentas, consulta do vocabulário e recusa de pergunta externa. O `RagClient` existente do Invenio consultou a API HTTP do piloto sem alteração. O modelo local também selecionou uma evidência real do vocabulário. A preparação original não executou esses fluxos. A etapa seguinte conectou e validou o fluxo real da interface, MCP e acesso público na homologação; consulte o relatório da integração local. Fine-tuning e implantação remota continuam pendentes.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.evaluate_corpus --output storage/retrieval-evaluation.json
```

As evidências estão em `output/argiloclay-intelligence-20261021/` na raiz da homologação. Para voltar à implantação anterior basta manter o Invenio apontando à porta 7860; o piloto usa 7861 e não alterou a configuração remota.

## Recursos de desenvolvimento verificados

As skills locais de RAG e arquitetura já cobrem a integração inicial. Foram encontrados no GitHub os recursos oficiais [Hugging Face Skills](https://github.com/huggingface/skills), especialmente [local models](https://github.com/huggingface/skills/tree/main/skills/huggingface-local-models), [LLM trainer](https://github.com/huggingface/skills/tree/main/skills/huggingface-llm-trainer) e [community evals](https://github.com/huggingface/skills/tree/main/skills/huggingface-community-evals). Não foram instaladas skills externas ou autorizados jobs pagos.

O MCP usa a linha 1.x do [SDK oficial Python](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), com dependência `<2` e versão efetivamente instalada registrada no lock. A documentação já distingue v1 da atual v2; atualizar exige revisão de compatibilidade. [llama.cpp](https://github.com/ggml-org/llama.cpp) é alternativa para investigar uma compilação compatível com essa CPU antiga. O Ollama remoto existente foi preservado. Parâmetros de inferência e saída seguem a [API oficial de chat do Ollama](https://docs.ollama.com/api/chat).
