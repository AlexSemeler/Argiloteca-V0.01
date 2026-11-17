"""Administrative OpenAlex extraction and bibliographic draft import."""
import os
from pathlib import Path


def configure(app):
    from . import models
    app.config.setdefault('ARGILOTECA_OPENALEX_ROOT', os.environ.get('ARGILOTECA_OPENALEX_ROOT', ''))
    app.config.setdefault('ARGILOTECA_OPENALEX_QUEUE', os.environ.get('ARGILOTECA_OPENALEX_QUEUE', str(Path(app.instance_path) / 'data/openalex-queue')))
    app.config.setdefault('ARGILOTECA_OPENALEX_BACKUPS', str(Path(app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'duplicate-backups'))
    app.config.setdefault('ARGILOTECA_ORCID_READ_PUBLIC_TOKEN', os.environ.get('ARGILOTECA_ORCID_READ_PUBLIC_TOKEN', ''))
    imports = list(app.config.get('CELERY_IMPORTS', ()))
    if 'argiloteca.openalex.tasks' not in imports:
        imports.append('argiloteca.openalex.tasks')
    app.config['CELERY_IMPORTS'] = tuple(imports)
    app.config.setdefault('CELERY_BEAT_SCHEDULE', {})['argiloteca-openalex-recovery'] = {
        'task': 'argiloteca.openalex.tasks.recover', 'schedule': 30.0,
        'options': {'expires': 25}}
    if app.config['ARGILOTECA_OPENALEX_ROOT'] and 'argiloteca_openalex' not in app.blueprints:
        from .views import blueprint
        from . import publication_views  # Register publication routes on the protected blueprint.
        from . import enrichment_views
        from . import analytics_views
        from .acervo import configure as configure_acervo
        configure_acervo(app)
        app.register_blueprint(blueprint)
        from .maintenance_views import blueprint as maintenance_blueprint
        app.register_blueprint(maintenance_blueprint)
