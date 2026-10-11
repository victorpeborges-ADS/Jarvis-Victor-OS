#!/bin/zsh
# Uso diário local. A passphrase fica só na memória do processo.
# Não grava credencial, não imprime o valor e não escolhe o banco estável
# quando JARVIS_DATABASE_PATH já aponta para um teste.
emulate -L zsh
set -eu
set -o pipefail

ROOT=${0:A:h:h}
cd "$ROOT"

if [[ -z ${JARVIS_LOCAL_PASSPHRASE-} ]]; then
  if [[ ! -t 0 ]]; then
    print -u2 "Execute este script em um Terminal para digitar a passphrase sintética. Nada foi gravado."
    exit 1
  fi
  read -r -s "JARVIS_LOCAL_PASSPHRASE?Passphrase sintética local: "
  print -u2
  byte_count=$(printf %s "$JARVIS_LOCAL_PASSPHRASE" | wc -c | tr -d '[:space:]')
  if (( byte_count < 12 || byte_count > 128 )); then
    unset JARVIS_LOCAL_PASSPHRASE
    print -u2 "Use entre 12 e 128 bytes. A passphrase não foi gravada."
    exit 1
  fi
fi
export JARVIS_LOCAL_PASSPHRASE

export JARVIS_API_ROOT=${JARVIS_API_ROOT:-$ROOT/apps/api}
if [[ ! -f $JARVIS_API_ROOT/serve.py ]]; then
  print -u2 "JARVIS_API_ROOT não contém serve.py."
  exit 1
fi

BIN=$ROOT/apps/desktop/src-tauri/target/release/desktop
if [[ ! -x $BIN ]]; then
  print -u2 "Binário release ausente. Em apps/desktop: npm ci && npm run tauri -- build --no-bundle"
  exit 1
fi

if [[ -n ${JARVIS_DATABASE_PATH-} ]]; then
  print -u2 "Banco de teste indicado por JARVIS_DATABASE_PATH. O banco estável não será usado."
else
  print -u2 "Banco estável: ~/Library/Application Support/Jarvis/memory.sqlite3"
fi
exec "$BIN"
