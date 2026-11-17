# Bounded dependency-only update for an already-built HML application image.
# The canonical Dockerfile/uv.lock reproduce the same pin on a full rebuild.
# Build with a minimal context containing uv.lock, argiloteca-custom.pyproject.toml
# and check_scientific_runtime.py; no application code, assets or data are rebuilt.
ARG HML_BASE_IMAGE=argiloteca-rdm14-hml:14.0.4
FROM ${HML_BASE_IMAGE}

COPY uv.lock /opt/invenio/src/uv.lock
COPY argiloteca-custom.pyproject.toml /opt/invenio/src/argiloteca_custom/pyproject.toml
COPY check_scientific_runtime.py /opt/invenio/src/scripts/check_scientific_runtime.py

RUN uv pip install --python /opt/invenio/src/.venv/bin/python \
      --no-deps --only-binary :all: 'numpy==2.3.5' && \
    uv pip check --python /opt/invenio/src/.venv/bin/python && \
    python /opt/invenio/src/scripts/check_scientific_runtime.py --timeout 30
