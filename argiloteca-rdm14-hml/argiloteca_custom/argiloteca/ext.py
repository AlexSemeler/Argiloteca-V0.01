# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: ext.py
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


class ArgilotecaUIExtension:
    """Extensão UI da Argiloteca."""

    def __init__(self, app=None):
        """
        Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
        
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
        Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
        
        Args:
            app: Valor de entrada consumido por esta etapa do fluxo.
        Returns:
            Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
        Raises:
            Exception: Propaga erros das dependências quando a validação ou o processamento falha.
        """
        # A namespaced loader lets the local deposit override extend the real
        # installed template, without copying it or recursively extending itself.
        from jinja2 import ChoiceLoader, PrefixLoader, PackageLoader
        app.jinja_loader = ChoiceLoader([
            PrefixLoader({
                "argiloteca_native": PackageLoader("invenio_app_rdm", "records_ui/templates/semantic-ui"),
                "argiloteca_admin_native": PackageLoader("invenio_administration", "templates/semantic-ui"),
            }),
            app.jinja_loader,
        ])
        from .openalex import configure as configure_openalex
        configure_openalex(app)
        from .pangaea import configure as configure_pangaea
        configure_pangaea(app)
        from .mendeley import configure as configure_mendeley
        configure_mendeley(app)
        from .repositories import configure as configure_repositories
        configure_repositories(app)
        from .population import configure as configure_population
        configure_population(app)
        bp = create_blueprint(app)
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)
        from .scientific.views import create_blueprint as scientific_blueprint
        if "argiloteca_scientific" not in app.blueprints:
            app.register_blueprint(scientific_blueprint(app))
        from .admin_ui import configure as configure_admin_ui
        configure_admin_ui(app)
        from .scientific.oai import validate_prefix
        app.before_request(validate_prefix)
        from .argiloclay.tasks import configure as configure_argiloclay_sync
        configure_argiloclay_sync(app)
        from .argiloclay.admin import register as register_knowledge
        register_knowledge(app)
        app.extensions["argiloteca_ui"] = self
