"""Mendeley Data administrative import; enabled by default only on loopback."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def configure(app):
    local = urlsplit(app.config.get('SITE_UI_URL', '')).hostname in {'127.0.0.1', 'localhost', '::1'}
    app.config.setdefault('ARGILOTECA_MENDELEY_ENABLED', os.environ.get('ARGILOTECA_MENDELEY_ENABLED', str(local)).lower() == 'true')
    if not app.config['ARGILOTECA_MENDELEY_ENABLED']:
        return
    app.config.setdefault('ARGILOTECA_MENDELEY_ROOT', str(Path(app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'mendeley'))
    from .views import blueprint
    from . import publication_views
    app.register_blueprint(blueprint)
