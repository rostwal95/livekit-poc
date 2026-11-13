#!/bin/sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "${SCRIPT_DIR}/.."
exec "${HARNESS_PYTHON:-python3}" -m harness.static_check --run-tests "$@"
