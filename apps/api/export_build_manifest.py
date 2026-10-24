"""Snapshot of the candidate worktree. This is not GET /v1/version."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "g6" / "BUILD_MANIFEST_2026-10-17.md"
PROTOCOL_BUILD = "g6-mac-002-3-locked-storage-v3"


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.rstrip("\n")


def _require(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise SystemExit(f"{path.relative_to(ROOT)} não contém {needle}")


def _package_version(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        return "ausente"
    return str(json.loads(path.read_text(encoding="utf-8")).get("version", "ausente"))


def main() -> None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head = _git("rev-parse", "HEAD")
    if branch != "codex/jarvis-integration-candidate":
        raise SystemExit(f"branch inesperada: {branch}")
    _require(ROOT / "apps/api/native_runtime.py", f'BUILD_ID = "{PROTOCOL_BUILD}"')
    _require(ROOT / "apps/desktop/src-tauri/src/transport.rs", f'const BUILD_ID: &str = "{PROTOCOL_BUILD}"')
    _require(ROOT / "apps/api/serve.py", "--desktop-runtime")
    _require(ROOT / "apps/api/serve.py", "JARVIS_BIND_HOST")
    _require(ROOT / "apps/api/native_runtime.py", 'f"build={BUILD_ID}\\n"')
    entries = []
    for line in _git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path == OUTPUT.relative_to(ROOT).as_posix():
            continue
        full = ROOT / path
        digest = hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else "não é arquivo"
        entries.append((line[:2], path, digest))
    lines = [
        "# Manifesto de build — candidata local",
        "",
        "Este arquivo não é o endpoint `GET /v1/version`. Esse endpoint identifica só",
        "`protocol_version`, `runtime_kind`, `instance_id` e `build`. O valor de `build`",
        f"conferido nos dois lados do transporte é `{PROTOCOL_BUILD}`. Ele não é o SHA do Git.",
        "",
        "O próprio manifesto fica de fora da lista de hashes: ele é o snapshot, não uma fonte.",
        "",
        "## Identidade",
        "",
        f"- Branch: `{branch}`",
        f"- HEAD: `{head}`",
        "- Frontend desktop: `apps/desktop`, versão "
        f"`{_package_version('apps/desktop/package.json')}`",
        "- Frontend web: `apps/web`, versão "
        f"`{_package_version('apps/web/package.json')}`",
        "- Runtime: `apps/api/serve.py`",
        "  - sem argumentos: API web, host `JARVIS_BIND_HOST` ou `127.0.0.1`, porta `JARVIS_BIND_PORT` ou `8000`, objeto `create_app`",
        "  - `--desktop-runtime <id>`: socket `runtime.sock`, prontidão `JARVIS_RUNTIME_READY <id>`",
        f"- Build de protocolo: `{PROTOCOL_BUILD}`",
        "",
        "## Diferenças locais",
        "",
        "| Estado | Caminho | SHA-256 do conteúdo |",
        "|---|---|---|",
    ]
    for state, path, digest in entries:
        lines.append(f"| `{state}` | `{path}` | `{digest}` |")
    lines.extend([
        "",
        "Nada nesta lista foi staged por este gerador. Banco diário, conta e efeito externo não entram.",
        "",
    ])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
