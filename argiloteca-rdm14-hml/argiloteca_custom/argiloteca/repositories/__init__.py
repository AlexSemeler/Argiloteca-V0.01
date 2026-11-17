"""Repositórios OAI administrative import; enabled by default only on loopback."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def configure(app):
    local = urlsplit(app.config.get('SITE_UI_URL', '')).hostname in {'127.0.0.1', 'localhost', '::1'}
    app.config.setdefault('ARGILOTECA_REPOSITORIES_ENABLED', os.environ.get('ARGILOTECA_REPOSITORIES_ENABLED', str(local)).lower() == 'true')
    if not app.config['ARGILOTECA_REPOSITORIES_ENABLED']:
        return
    app.config.setdefault('ARGILOTECA_REPOSITORIES_ROOT', str(Path(app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'repositories'))
    from .views import blueprint
    from . import publication_views, pdf_views
    app.register_blueprint(blueprint)
