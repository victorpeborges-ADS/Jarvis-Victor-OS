#!/bin/zsh
# Sobe o aplicativo macOS local sem imprimir credenciais.
# Não abre TCP, não chama Google e não grava a passphrase.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${JARVIS_LOCAL_PASSPHRASE:-}" || -z "${JARVIS_DATABASE_PATH:-}" ]]; then
  echo "Defina JARVIS_LOCAL_PASSPHRASE e JARVIS_DATABASE_PATH no ambiente. Os valores não são impressos." >&2
  exit 1
fi
export JARVIS_API_ROOT="${JARVIS_API_ROOT:-$ROOT/apps/api}"
if [[ ! -f "$JARVIS_API_ROOT/serve.py" ]]; then
  echo "JARVIS_API_ROOT não contém serve.py." >&2
  exit 1
fi
BIN="$ROOT/apps/desktop/src-tauri/target/release/desktop"
if [[ ! -x "$BIN" ]]; then
  echo "Binário release ausente. Em apps/desktop, com as mesmas variáveis, execute: npm run tauri -- build --no-bundle" >&2
  exit 1
fi
exec "$BIN"
