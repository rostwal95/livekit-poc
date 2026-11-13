#!/bin/sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "${SCRIPT_DIR}/.."
module=all
while [ "$#" -gt 0 ]; do
  case "$1" in
    --module)
      if [ "$#" -lt 2 ]; then printf '%s\n' '--module requires p1, p2, p3, or all' >&2; exit 2; fi
      module="$2"; shift 2 ;;
    -h|--help)
      printf '%s\n' 'Usage: scripts/harness-deep.sh [--module p1|p2|p3|all]' \
        'Runs registered acceptance cases; planned cases return incomplete (exit 2).'
      exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
case "$module" in p1|p2|p3|all) ;; *) printf 'Unknown module: %s\n' "$module" >&2; exit 2 ;; esac
exec "${HARNESS_PYTHON:-python3}" -m harness run --project "$module"
