# Use Docker's bundled BuildKit frontend for reproducible local builds.
#
# SPDX-FileCopyrightText: 2026 Northwestern University.
# SPDX-FileCopyrightText: 2026 Frontmatter.
# SPDX-FileCopyrightText: 2026 KTH Royal Institute of Technology.
# SPDX-License-Identifier: MIT
ARG BUILDPLATFORM

FROM ghcr.io/inveniosoftware/invenio:14-debian@sha256:d1b42add770e247e788e4c7798fde887e1c9d822c19c15f074631af91f2d6d54 AS base

FROM base AS builder

COPY README.md pyproject.toml uv.lock ./
COPY site ./site
COPY argiloteca_custom ./argiloteca_custom
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Fail the build if the scientific runtime cannot perform a normal cold import.
COPY ./scripts/check_scientific_runtime.py /tmp/check_scientific_runtime.py
RUN python /tmp/check_scientific_runtime.py --timeout 30

COPY ./docker/uwsgi/ ${INVENIO_INSTANCE_PATH}
COPY ./invenio.cfg ${INVENIO_INSTANCE_PATH}
COPY ./templates/ ${INVENIO_INSTANCE_PATH}/templates/
COPY ./app_data/ ${INVENIO_INSTANCE_PATH}/app_data/
COPY ./translations/ ${INVENIO_INSTANCE_PATH}/translations/
COPY ./assets/ ./assets/
COPY ./static/ ./static/
COPY ./scripts/manage_translations.py ./scripts/install_frontend_translations.py /tmp/

RUN python /tmp/manage_translations.py compile --root ${INVENIO_INSTANCE_PATH} --catalogs-only

RUN cp -r ./static/. ${INVENIO_INSTANCE_PATH}/static/ && \
    cp -r ./assets/. ${INVENIO_INSTANCE_PATH}/assets/ && \
    invenio collect --verbose && \
    invenio webpack create && \
    python /tmp/install_frontend_translations.py ${INVENIO_INSTANCE_PATH}/translations/frontend ${INVENIO_INSTANCE_PATH}/assets

FROM --platform=${BUILDPLATFORM} node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS assets-builder

ENV INVENIO_INSTANCE_PATH=/opt/invenio/var/instance
WORKDIR ${INVENIO_INSTANCE_PATH}/assets

RUN corepack enable pnpm && \
    corepack install --global pnpm@11.27.1

COPY --from=builder ${INVENIO_INSTANCE_PATH}/assets/ ${INVENIO_INSTANCE_PATH}/assets/
COPY --from=builder ${INVENIO_INSTANCE_PATH}/static/ ${INVENIO_INSTANCE_PATH}/static/
COPY package.json /tmp/argiloteca-locked-package.json
COPY pnpm-lock.yaml ${INVENIO_INSTANCE_PATH}/assets/pnpm-lock.yaml

RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    cmp /tmp/argiloteca-locked-package.json ${INVENIO_INSTANCE_PATH}/assets/package.json && \
    pnpm install --frozen-lockfile && \
    pnpm run build && \
    rm -rf \
        /root/.cache \
        /tmp/* \
        ${INVENIO_INSTANCE_PATH}/assets/node_modules \
        ${INVENIO_INSTANCE_PATH}/assets/.cache

FROM base AS app-base

COPY . .
COPY --from=builder ${WORKING_DIR}/src/.venv ./.venv
COPY --from=assets-builder ${INVENIO_INSTANCE_PATH}/static/ ${INVENIO_INSTANCE_PATH}/static/
COPY --from=assets-builder ${INVENIO_INSTANCE_PATH}/static/ /opt/invenio/static-dist/
COPY ./docker/uwsgi/ ${INVENIO_INSTANCE_PATH}
COPY ./invenio.cfg ${INVENIO_INSTANCE_PATH}
COPY ./templates/ ${INVENIO_INSTANCE_PATH}/templates/
COPY ./app_data/ ${INVENIO_INSTANCE_PATH}/app_data/
COPY ./translations/ ${INVENIO_INSTANCE_PATH}/translations/
COPY --from=builder ${INVENIO_INSTANCE_PATH}/translations/ ${INVENIO_INSTANCE_PATH}/translations/

ENTRYPOINT ["bash", "-c"]
