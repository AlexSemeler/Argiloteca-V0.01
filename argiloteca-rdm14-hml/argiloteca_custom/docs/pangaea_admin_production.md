# Importação PANGAEA em produção

Implantada e validada em 31/10/2026. Acesse **Povoamento → Importação PANGAEA** na administração ou abra [o módulo](https://vmx000080.nuvem.ufrgs.br/administration/pangaea/?ln=pt).

O fluxo é o descrito no [guia de operação](pangaea_admin_local.md): escolher um dos 81 argilominerais, uma expressão livre ou ambos; coletar; revisar/corrigir; selecionar comunidades; importar; conferir e confirmar a publicação em etapa separada. Consultas combinadas agrupam o texto livre com AND e os nomes inglês/português do mineral com OR. DOI é usado para atualizar o mesmo registro, preservando arquivos, campos científicos, acesso e vínculos anteriores.

Em produção a coleta roda no serviço Linux `pangaea-agent`, com reinício automático e healthcheck. Não execute o instalador launchd do Mac no servidor. O agente compartilha a fila persistente do aplicativo, na subpasta `pangaea`, e usa a rede de saída já existente; não expõe portas públicas.

Há uma [revisão real pronta](https://vmx000080.nuvem.ufrgs.br/administration/pangaea/jobs/4f67b91740a941ba8b28587f4605be69?ln=pt), obtida com Caulinita + `"Aegean Sea"`. Ela aguarda seleção e confirmação; a validação produtiva não importou ou publicou registros.

Foram aprovados 65 testes na imagem candidata, o ciclo nativo completo em clone isolado e uma coleta/preparação real pela fila produtiva. As 19 tabelas nativas verificadas, o Acervo de 6.391 registros, os assets e o conteúdo analítico foram preservados. O relatório completo e os recibos ficam na raiz do workspace em `output/pangaea-production-20261031/RELATORIO_IMPLANTACAO.md`.

Imagem ativa: `argiloteca-rdm14-prod:14.0.4-20261031-pangaea`. Configuração persistida: `/home/vmx000080/argiloteca-rdm14-production/runtime/compose.yml`. Backup criptografado do banco, composição anterior e recuperação de código preparados em `/home/vmx000080/argiloteca-pangaea-20261031/`, sob acesso privado no servidor. A reversão de código preserva o banco e as operações posteriores; não execute restauração de banco como rollback automático da aplicação.
