# Argiloteca

A Argiloteca é um repositório digital para organizar e consultar informações
científicas sobre argilas e argilominerais. O projeto conecta amostras,
localidades, publicações, métodos analíticos e resultados, com rastreabilidade
dos metadados e suporte a difração de raios X (DRX).

## O que este repositório contém

- A aplicação baseada em InvenioRDM 14.0.4 e suas extensões científicas.
- Interfaces, documentação, traduções em português e inglês e configurações
  versionáveis para desenvolvimento e homologação.
- Código de apoio para catálogo mineral, metadados científicos, integração com
  fontes bibliográficas e ferramentas de análise.

O diretório principal da aplicação é
[`argiloteca-rdm14-hml/`](argiloteca-rdm14-hml/). Consulte o
[guia da aplicação](argiloteca-rdm14-hml/README.md) e o documento de
[interface](argiloteca-rdm14-hml/INTERFACE.md) para detalhes de arquitetura e
operação.

## Requisitos e execução

A aplicação de homologação usa Docker Compose e InvenioRDM 14.0.4. Para
requisitos, configuração do ambiente local e comandos de operação, siga o
[guia da aplicação](argiloteca-rdm14-hml/README.md).

Este repositório contém o código e a documentação, mas não inclui credenciais,
bancos de dados, arquivos científicos locais, corpus DRX, backups ou pesos de
modelos. Uma instalação funcional precisa ser configurada com os dados e
serviços apropriados no ambiente de destino. O guia descreve a homologação
local; ela não configura nem autoriza uma implantação em produção.

## Segurança e dados locais

Não adicione senhas, chaves de API, tokens, certificados privados, arquivos
`.env`, bases locais, filas, backups ou relatórios de execução ao Git. O
`.gitignore` da raiz exclui esses itens e diretórios de trabalho gerados. O
arquivo `argiloteca-rdm14-hml/.env.example` contém somente nomes de variáveis e
valores de exemplo; gere credenciais locais próprias conforme o guia.

Antes de preparar um commit, confira a lista de arquivos com:

```bash
git status --short
git diff --cached --stat
```

## Licença

Este repositório ainda não declara uma licença. Defina a licença antes de
autorizar reutilização ou distribuição do código.
