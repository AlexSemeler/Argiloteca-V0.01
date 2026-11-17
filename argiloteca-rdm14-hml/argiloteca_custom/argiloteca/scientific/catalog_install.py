"""Run with python -m argiloteca.scientific.catalog_install in the application runtime."""
import json
from invenio_app.factory import create_ui
from .install import install
from .catalog import install_catalog

if __name__ == '__main__':
    app = create_ui()
    with app.test_request_context():
        print(json.dumps({'installation': install(app), 'catalog': install_catalog()}, ensure_ascii=False, indent=2))
