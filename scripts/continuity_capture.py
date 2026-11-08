#!/usr/bin/env python3
"""Checkpoint técnico local e privado; nunca copia chats, prompts, diffs ou logs."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

EVENTS = {"manual", "before", "after", "commit", "error"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, timeout=15, check=True).stdout.strip()


def paths(repo):
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    target = Path(git(root, "rev-parse", "--git-path", "continuity/checkpoint.json"))
    return root, target if target.is_absolute() else root / target


def branch_name(repo):
    try:
        return git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    except subprocess.CalledProcessError:
        return "(detached)"


def capture(repo, event="manual", exit_code=None):
    if event not in EVENTS:
        raise ValueError("Evento inválido")
    root, output = paths(repo)
    tracked = git(root, "status", "--porcelain=v1", "-uno")
    untracked = git(root, "ls-files", "--others", "--exclude-standard")
    doc = {
        "schema_version": 1, "project": "Jarvis Victor OS",
        "classification": "GIT_OBSERVADO_NAO_QA", "sensitivity": "PRIVATE_LOCAL",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": event, "branch": branch_name(root),
        "commit": git(root, "rev-parse", "HEAD"),
        "tracked_changes": len(tracked.splitlines()) if tracked else 0,
        "untracked_files": len(untracked.splitlines()) if untracked else 0,
        "exit_code": exit_code if type(exit_code) is int and 0 <= exit_code <= 255 else None,
        "canonical_documents": ["AGENTS.md", "docs/CHECKPOINT_ATUAL_JARVIS.md",
                                "docs/PROTOCOLO_CONTINUIDADE_CONVERSAS.md"],
        "limitations": ["Não mede o contexto do ChatGPT.",
                        "Não valida testes nem execução de ferramentas externas.",
                        "Decisões e handoff narrativo continuam dependentes de evidências."],
    }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(output.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".checkpoint-", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if os.name == "posix":
                os.fchmod(f.fileno(), 0o600)
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, output)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return doc, output


def resume(repo):
    root, output = paths(repo)
    data = json.loads(output.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("project") != "Jarvis Victor OS":
        raise ValueError("Checkpoint inválido")
    return (
        "Continue o Jarvis Victor OS. Leia AGENTS.md, docs/CHECKPOINT_ATUAL_JARVIS.md "
        "e docs/PROTOCOLO_CONTINUIDADE_CONVERSAS.md. Última captura: "
        f"branch={data['branch']} commit={data['commit'][:12]} "
        f"tracked={data['tracked_changes']} untracked={data['untracked_files']} "
        f"em {data['timestamp_utc']}. Verifique o estado ATUAL e as fontes. "
        "Não presuma aceite, testes atuais ou novas autorizações. Preserve worktrees, "
        "alterações locais, backups e privacidade. Ao fechar o ciclo, crie outro checkpoint."
    )


def main():
    p = argparse.ArgumentParser(description="Continuidade local sem dados de conversa")
    p.add_argument("--repo", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--event", default="manual", choices=sorted(EVENTS))
    sub.add_parser("resume")
    x = sub.add_parser("run")
    x.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.action == "resume":
        print(resume(args.repo))
        return 0
    if args.action == "capture":
        doc, output = capture(args.repo, args.event)
        print(json.dumps({"checkpoint": str(output), "event": doc["event"],
                          "commit": doc["commit"][:12]}, ensure_ascii=False))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        p.error("Indique um comando após --")
    root, _ = paths(args.repo)
    capture(root, "before")
    try:
        # O wrapper NÃO captura stdout, stderr, comandos ou conteúdo dos arquivos.
        rc = subprocess.run(command, cwd=root, check=False).returncode
    except OSError:
        capture(root, "error")
        raise
    capture(root, "after", exit_code=rc if 0 <= rc <= 255 else None)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print("Checkpoint não concluído: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
