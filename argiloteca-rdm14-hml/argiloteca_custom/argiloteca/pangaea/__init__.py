"""PANGAEA administrative import, using the shared durable import journal."""
from pathlib import Path


def configure(app):
    app.config.setdefault('ARGILOTECA_PANGAEA_ROOT', str(Path(
        app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'pangaea'))
    from .views import blueprint
    from . import publication_views
    app.register_blueprint(blueprint)
