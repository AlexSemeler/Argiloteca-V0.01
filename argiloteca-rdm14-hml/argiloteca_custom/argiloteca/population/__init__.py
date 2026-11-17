"""Integrated population dashboard, opt-in outside the local instance."""
import os
from urllib.parse import urlsplit


def configure(app):
    local = urlsplit(app.config.get('SITE_UI_URL', '')).hostname in {'localhost', '127.0.0.1', '::1'}
    app.config.setdefault('ARGILOTECA_POPULATION_ENABLED', os.environ.get('ARGILOTECA_POPULATION_ENABLED', str(local)).lower() == 'true')
    if app.config['ARGILOTECA_POPULATION_ENABLED'] and app.config.get('ARGILOTECA_OPENALEX_ROOT'):
        from .views import blueprint
        app.register_blueprint(blueprint)
