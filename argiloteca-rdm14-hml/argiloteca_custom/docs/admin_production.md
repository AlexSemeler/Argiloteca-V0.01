# Administração em produção

**Atualização de 02/11/2026:** somente a interface recebeu a imagem `14.0.4-20261102-search-accent`, que mantém a [ajuda de pesquisa em português e inglês, com largura ampliada](search_help_pt.md), corrige o telefone do rodapé para `51 3308 – 65 69` e inclui um ícone clicável do WhatsApp para `https://wa.me/555133086569`, com nome acessível e sem texto visível. A frase de busca em português usa “método analítico” e “contexto geológico”, com acentuação corrigida. API, workers e coletores mantêm a versão administrativa abaixo.

Os ajustes administrativos foram implantados em **01/11/2026**. Abra [Administração](https://vmx000080.nuvem.ufrgs.br/administration/?ln=pt) ou [Povoamento integrado](https://vmx000080.nuvem.ufrgs.br/administration/povoamento/?ln=pt).

A versão produtiva inclui organização por ontologia, cores e marcas, mapa/topônimos, OpenAlex/PANGAEA/Mendeley/OAI, PDFs, estatísticas e autores/ORCID integrados, seleção de página e remoção com prévia. Mendeley e OAI têm coletores Linux próprios; não dependem do Mac. Registros e lotes da homologação não foram migrados.

Os fluxos dos guias [administração e mapa](admin_ontology_local.md) e [seleção e remoção](admin_bulk_local.md) permanecem aplicáveis. As URLs locais nesses guias documentam os ensaios históricos; em produção use o domínio acima. Não aplique o override Compose local ao servidor: as flags e montagens produtivas já estão persistidas no runtime.

ORCID remove somente o identificador da autoria selecionada, preservando autor e publicações. A exclusão RAW remove binários anônimos e cópias DRX selecionados e seus vínculos ativos; originais privados, resultados históricos e backups permanecem arquivados. Prévia, permissões, dependências, justificativa, confirmação **EXCLUIR** e backup verificado continuam obrigatórios. Não há restauração automática pela interface.

Imagem ativa: `argiloteca-rdm14-prod:14.0.4-20261101-administration`. Foram aprovados 406 testes na candidata e verificações produtivas em PT/EN, desktop/celular e topônimo. As 19 tabelas nativas, os 6.391 registros do catálogo público, 2.476 assets compilados e 9.946 arquivos físicos da biblioteca histórica foram preservados. Nenhum registro ou RAW científico produtivo foi importado, publicado ou excluído na validação.

Consulte o [relatório da implantação](../../../output/admin-production-20261101/RELATORIO_IMPLANTACAO.md) para recibos, backups, limites e reversão de código. O backup criptografado foi restaurado apenas em clone privado; sua chave permanece no servidor. A reversão preparada preserva o banco e as exclusões RAW posteriores, sem restaurar dados automaticamente.
