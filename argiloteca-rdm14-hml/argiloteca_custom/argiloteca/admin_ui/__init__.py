"""Local administration information architecture, without metadata mutations."""
import os
from urllib.parse import urlsplit


def configure(app):
    local = urlsplit(app.config.get('SITE_UI_URL', '')).hostname in {'localhost', '127.0.0.1', '::1'}
    app.config.setdefault('ARGILOTECA_ADMIN_ONTOLOGY_ENABLED', os.environ.get('ARGILOTECA_ADMIN_ONTOLOGY_ENABLED', str(local)).lower() == 'true')
    if not app.config['ARGILOTECA_ADMIN_ONTOLOGY_ENABLED']:
        return
    from .views import blueprint
    from .navigation import context
    app.register_blueprint(blueprint)
    app.context_processor(context)
