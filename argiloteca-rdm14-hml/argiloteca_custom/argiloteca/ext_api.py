# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: ext_api.py
#
# Descrição.........:
# Integra componentes do Painel de DRX da Argiloteca.
#
# Autor.............:
# Alexandre Ribas Semeler
# alexandre.semeler@ufrgs.br
#
# Última atualização:
# 2026-06-25
#
# =============================================================================

"""
Projeto: Painel DRX Argiloteca

Descrição:
Componente do pacote Argiloteca Custom usado para integrar serviços científicos, visualizações e metadados ao InvenioRDM.

Autores:
- Alexandre Ribas Semeler
  E-mail: alexandre.semeler@ufrgs.br



Projeto:
Argiloteca / CPAA

Licença:
Preservar licença existente no repositório.

Última revisão:
2026-06-21

Observação:
Este arquivo integra o sistema de análise, comparação e interpretação de difratogramas de raios X para argilominerais.
"""

from .views import create_blueprint


class ArgilotecaAPIExtension:
    """Extensão API da Argiloteca."""

    def __init__(self, app=None):
        """
        Atende uma chamada da interface ou API, convertendo dados internos em resposta estável para o painel web.
        
        Args:
            app: Valor de entrada consumido por esta etapa do fluxo.
        Returns:
            Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
        Raises:
            Exception: Propaga erros das dependências quando a validação ou o processamento falha.
        """
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Atende uma chamada da interface ou API, convertendo dados internos em resposta estável para o painel web.
        
        Args:
            app: Valor de entrada consumido por esta etapa do fluxo.
        Returns:
            Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
        Raises:
            Exception: Propaga erros das dependências quando a validação ou o processamento falha.
        """
        from .openalex import configure as configure_openalex
        configure_openalex(app)
        bp = create_blueprint(app)
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)
        from .scientific.views import create_blueprint as scientific_blueprint
        if "argiloteca_scientific" not in app.blueprints:
            app.register_blueprint(scientific_blueprint(app))
        app.extensions["argiloteca_api"] = self
