#!/usr/bin/env bash
# Creates lib/secrets/fallback.dart from the committed stub.
#
# lib/secrets/ is gitignored, because that is where a developer's own key lives.
# A fresh clone therefore has no such file, and `dart analyze` fails on the
# unconditional imports in model_provider.dart and chat_api_helpers.dart. Run
# this once after cloning; the tree then compiles with an empty fallback.
#
# Overwrite lib/secrets/fallback.dart with your own key if you want the fallback
# to actually fire. Nothing here ever puts a key in version control.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stub="$here/stubs/fallback.dart"
target="$here/../lib/secrets/fallback.dart"

if [ ! -f "$stub" ]; then
  echo "missing $stub" >&2
  exit 1
fi

mkdir -p "$(dirname "$target")"
cp "$stub" "$target"
echo "wrote $target from $stub"
