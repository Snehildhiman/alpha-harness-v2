#!/bin/sh
# Regenerate the frontend's API types from the backend's OpenAPI schema.
#   generate.sh <output.ts>          write the types there
#   generate.sh --check <current.ts> fail if <current.ts> is stale
# Run from the repository root.
set -eu
mode=write
if [ "${1:-}" = "--check" ]; then mode=check; shift; fi
target=${1:?output path}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM HUP

(cd backend && uv run --quiet python -m alpha_harness.openapi) > "$work/openapi.json"
pnpm --silent --dir frontend/tools/codegen exec openapi-typescript "$work/openapi.json" \
  -o "$work/generated.ts" >/dev/null

if [ "$mode" = check ]; then
  if ! cmp -s "$work/generated.ts" "$target"; then
    echo "$target is stale: the backend's API changed. Run: lefthook run format" >&2
    exit 1
  fi
else
  cp "$work/generated.ts" "$target"
fi
