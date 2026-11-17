# Aplicação Argiloteca (InvenioRDM 14.0.4)

Esta pasta contém a aplicação web da Argiloteca para homologação, baseada em
InvenioRDM 14.0.4. O pacote customizado reúne a interface do repositório e
extensões para metadados científicos, catálogo mineral e análise de difração de
raios X (DRX). A interface dispõe de traduções em português e inglês.

## Estrutura

- `argiloteca_custom/`: extensões Python, serviços científicos, templates,
  arquivos estáticos, scripts e testes.
- `docs/`: documentação funcional e técnica.
- `assets/`, `templates/`, `static/` e `translations/`: interface, recursos e
  catálogos de idioma.
- `docker-compose*.yml`, `Dockerfile`, `pyproject.toml` e `uv.lock`:
  configuração da aplicação e dependências.
- `services/argiloclay-intelligence/`: serviço auxiliar de inteligência e
  recuperação de informações, incluindo código e testes.

## Requisitos e configuração

A execução local usa Docker e Docker Compose. A aplicação também depende de
serviços e dados fornecidos pelo ambiente de homologação. Credenciais, bases,
corpus científicos, arquivos locais e pesos de modelos não fazem parte deste
repositório; um clone sozinho não recria a instância migrada.

Use `../README.md` como apresentação do projeto. Para preparar um ambiente,
revise os arquivos `docker-compose*.yml`, o `.env.example` e os scripts desta
pasta. Crie credenciais próprias para cada instalação e mantenha-as somente no
arquivo `.env` local. Nunca publique esse arquivo, chaves, certificados
privados ou dumps de banco de dados.

O script `./scripts/bootstrap` é destinado à criação de um esqueleto novo e
vazio. Não o execute sobre uma instalação migrada ou com dados existentes. Os
comandos `./scripts/start`, `./scripts/status`, `./scripts/test` e
`./scripts/stop` operam uma homologação já configurada com os serviços e dados
necessários.

## Testes e idioma

Os testes e verificações de metadados e ciência ficam em `tests/` e nos
subpacotes customizados. Eles dependem do ambiente e das bibliotecas definidos
para InvenioRDM 14.0.4; consulte a configuração de cada pacote antes de
executá-los.

Os catálogos de tradução ficam em `translations/`. Após alterar fontes de
tradução, use `./scripts/compile-translations` no ambiente preparado da
aplicação.

## Uso

Esta configuração foi preparada para desenvolvimento e homologação. Uma
instalação ou migração real requer provisionamento e validação próprios; o
código aqui não configura produção automaticamente.
