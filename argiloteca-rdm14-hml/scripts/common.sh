#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_NAME="argiloteca-rdm14-hml"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly ENV_FILE="${PROJECT_DIR}/.env"
readonly COMPOSE_FILE="${PROJECT_DIR}/docker-compose.full.yml"
readonly MIGRATED_COMPOSE_FILE="${PROJECT_DIR}/docker-compose.migrated.yml"

die() {
  printf 'ERRO: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "comando obrigatório ausente: $1"
}

require_env_file() {
  [[ -f "${ENV_FILE}" ]] || die "arquivo .env ausente; execute scripts/generate-env"
}

compose() {
  docker compose \
    --project-name "${PROJECT_NAME}" \
    --env-file "${ENV_FILE}" \
    --file "${COMPOSE_FILE}" \
    "$@"
}

compose_migrated() {
  docker compose \
    --project-name "${PROJECT_NAME}" \
    --env-file "${ENV_FILE}" \
    --file "${COMPOSE_FILE}" \
    --file "${MIGRATED_COMPOSE_FILE}" \
    "$@"
}
