# ARGILOCLAY conectado na homologação local

Integração de 21/10/2026. A conversa está disponível em **https://127.0.0.1:5101/argiloclay**. O launcher compartilhado leva o contexto da página ao mesmo assistente, incluindo Catálogo/Busca, registros, mapas, perfis minerais, vocabulários, Análises, comparação DRX, pacotes analíticos, comunidades, depósitos, administração e ajuda. Layout, mascote, histórico, diálogos, fontes, exportação e exemplos foram preservados.

## Caminho de uma consulta

1. O launcher transfere somente caminho, idioma, IDs e uma seleção curta. Um BroadcastChannel efêmero fornece até seis identidades de curvas; não transmite vetores, bytes de arquivo ou resultados científicos como fatos validados. A janela continua com `opener=null`.
2. A conversa envia a pergunta ao gateway `/argiloclay/api/query`, na mesma origem, com token CSRF. O Invenio valida o envelope e exige que os registros referenciados sejam publicados, públicos e acessíveis pela identidade atual. Contexto não concede permissão.
3. O piloto recebe a consulta pela rede Docker isolada. Um cliente MCP mantém um único processo stdio e escolhe ferramentas de forma determinística, sem loops de agentes: `search_evidence`, `lookup_vocabulary`, `get_public_record`, `get_section_guide`, `corpus_status`.
4. O RAG consulta o índice autorizado. O Qwen local pode selecionar somente IDs de trechos. O backend rejeita prosa livre, referências inventadas e respostas incompletas. O prazo do modelo é três segundos; falhas conservam a recuperação extrativa. Não há fine-tuning novo nesta integração.
5. Antes de devolver fontes de registros, o Invenio verifica novamente seu acesso público e `updated`. Fontes alteradas, excluídas ou restritas saem da resposta, que é reconstruída sem a prosa livre do serviço. O mesmo controle cobre o endpoint RAG legado do DRX quando recebe fontes de registros.
6. A interface renderiza texto literal e marcadores ligados ao trecho exato. Ao recarregar ou restaurar histórico com registros, esconde a resposta até `/argiloclay/api/verify` confirmar as fontes. Uma fonte revogada ou não verificável deixa de ser exibida.

Os guias das seções são documentos de uso derivados da implementação e identificados como documentação técnica. Têm referência e hash da fonte de implementação, além do hash do documento de guia. Não são literatura mineralógica nem nova análise de amostras.

## Processos e portas

| Componente | Endereço | Função |
| --- | --- | --- |
| Interface Invenio | https://127.0.0.1:5101/argiloclay | Conversa e gateway com permissões |
| Piloto Docker | http://127.0.0.1:7862 | RAG/MCP da integração local |
| Piloto de preparação anterior | http://127.0.0.1:7861 | Processo de desenvolvimento separado |
| Ollama isolado do projeto | http://127.0.0.1:11435 | Perfil `argiloclay-evidence:1.7b` |

O serviço Docker `argiloclay` usa 512 MiB, uma CPU, filesystem somente leitura, índices montados somente para leitura, fila limitada e um filho MCP. Os pesos permanecem no Ollama do host, fora do processo Invenio e do limite de memória desse contêiner.

O overlay local aponta `ARGILOCLAY_URL` e `ARGILOTECA_DRX_RAG_URL` para esse serviço. O modo de seleção pelo modelo é local, com `ARGILOCLAY_USE_MODEL=1` por padrão no overlay. Para desativá-lo, execute o Compose com essa variável em zero; a conversa continua documental e o MCP permanece ativo. O Ollama precisa estar iniciado conforme o README do piloto. Se não estiver, há fallback extrativo, sem substituir fontes por conhecimento prévio.

A operação diária continua com `./scripts/start` e `./scripts/status`. O início agora recarrega o Nginx após recriar contêineres web: seus endereços podem mudar, e o proxy resolve os nomes ao carregar a configuração. O status inclui a saúde do RAG/MCP. Não há alteração de banco, registros, RAWs ou implantação remota.

## Validação e limites

As evidências desta etapa ficam em `output/argiloclay-interface-20261021/` e `output/playwright/argiloclay-live/`, na raiz Git. Incluem testes unitários do gateway/workflow, contratos legados, HTTP real com CSRF/origem, recuperação, navegação por quinze páginas públicas, layouts autenticados por cliente de teste, conversa PT/EN, desktop/celular, citações, histórico e revogação simulada. Os casos de indisponibilidade incluem verificação de recuperação do serviço local.

A extração de fórmulas, sinais e tabelas dos PDFs conserva revisão numérica pendente. Números de referência não são medidas de uma amostra. Fontes mantêm seu idioma original; apenas textos da interface, guias e mensagens envolventes recebem localização. A nomenclatura e os IDs originais não foram alterados.

A seleção científica enviada pelo navegador é contexto de sessão, não uma evidência científica nova. Curvas temporárias não são publicadas e o assistente não confirma minerais, recalcula DRX, modifica depósitos ou lê rascunhos/restritos. O corpus remoto DRX anterior permanece intacto: sua fusão, benchmark na CPU remota e qualquer promoção são trabalhos posteriores, após revisão dos resultados locais.

## Rollback

As cópias iniciais da interface e do overlay desta etapa ficam em `output/argiloclay-interface-20261021/before/`. O serviço adicional pode ser parado independentemente. Não remover volumes ou índices para desfazer a conexão. O servidor remoto continua na configuração anterior.
