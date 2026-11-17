# Extração das rotas DRX de leitura

As rotas deste diretório são registradas no blueprint público existente
`argiloteca`. Essa estratégia preserva nomes como
`argiloteca.api_drx_registros`; o Flask não permite registrar um segundo
blueprint com o mesmo nome na mesma aplicação.

Foram extraídas rotas de renderização, RAG, curvas, snapshots, relatórios de
leitura, status, referências e evidência neural. Rotas de upload, importação,
persistência, submissão de jobs e fluxos científicos POST permanecem em
`views.py` até que seus efeitos sejam caracterizados.

`create_drx_blueprint(public_blueprint, dependencies)` é idempotente e recebe
dependências explícitas, evitando importações de `views.py` e ciclos.
