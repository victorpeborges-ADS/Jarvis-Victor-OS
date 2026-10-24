"""Ingestão de TXT e Markdown dentro de uma pasta aprovada.

Symlink, caminho fora da raiz, arquivo grande, formato recusado e item
ignorado não entram no índice. Pasta revogada não reindexa conteúdo novo.
A busca híbrida não é adotada: não houve ganho medido e não há índice novo.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from memory_categories import DOMAINS
from memory_store import SQLiteMemoryStore

MAX_BYTES = 4096
QUEUE_LIMIT = 4
_ALLOWED = {".txt", ".md"}
_REFUSED = {".zip", ".html", ".pdf", ".docx", ".xlsx", ".pptx", ".py", ".sh"}
_ROOT_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")


def _root_id(value: str) -> bool:
    return isinstance(value, str) and _ROOT_ID.fullmatch(value) is not None


def hybrid_search_decision() -> dict[str, str | bool]:
    return {"adopted": False, "reason": "sem_ganho_medido", "index": "literal"}


class IngestJob:
    def __init__(self, store: SQLiteMemoryStore, root: Path, domain_id: str, root_id: str) -> None:
        if domain_id not in DOMAINS or not _root_id(root_id):
            raise ValueError("ingestão recusada")
        if root.is_symlink() or not root.is_dir():
            raise ValueError("ingestão recusada")
        self._store = store
        self._root = root
        self._domain_id = domain_id
        self._root_id = root_id
        self._queue: list[str] = []
        self._paused = False
        self._cancelled = False
        self._ensure_root()

    def submit(self, relative: str) -> str:
        if self._revoked():
            return "revogada"
        if len(self._queue) >= QUEUE_LIMIT:
            return "fila_cheia"
        if not isinstance(relative, str) or relative == "":
            return "recusado"
        self._queue.append(relative)
        return "aceito"

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def cancel(self) -> None:
        self._cancelled = True
        self._queue.clear()

    def revoke(self) -> None:
        with self._store.transaction() as connection:
            connection.execute(
                "UPDATE approved_roots SET revoked = 1 WHERE root_id = ? AND owner = ?",
                (self._root_id, "owner"),
            )

    def step(self) -> dict[str, str | bool]:
        if self._revoked():
            return {"status": "revogada", "indexed": False, "missing": ""}
        if self._paused:
            return {"status": "pausa", "indexed": False, "missing": ""}
        if self._cancelled or not self._queue:
            return {"status": "cancelado" if self._cancelled else "vazio", "indexed": False, "missing": ""}
        relative = self._queue.pop(0)
        return self._index(relative)

    def excerpt(self, relative: str) -> str | None:
        with self._store.transaction() as connection:
            row = connection.execute(
                """SELECT excerpt, fingerprint FROM approved_files
                   WHERE owner = ? AND domain_id = ? AND root_id = ? AND relative_path = ?""",
                ("owner", self._domain_id, self._root_id, relative),
            ).fetchone()
        if row is None:
            return None
        return row[0]

    def fingerprint(self, relative: str) -> str | None:
        with self._store.transaction() as connection:
            row = connection.execute(
                """SELECT fingerprint FROM approved_files
                   WHERE owner = ? AND domain_id = ? AND root_id = ? AND relative_path = ?""",
                ("owner", self._domain_id, self._root_id, relative),
            ).fetchone()
        return None if row is None else row[0]

    def _ensure_root(self) -> None:
        with self._store.transaction() as connection:
            connection.execute(
                """INSERT INTO approved_roots(root_id, owner, domain_id, revoked)
                   VALUES (?, 'owner', ?, 0)
                   ON CONFLICT(root_id) DO NOTHING""",
                (self._root_id, self._domain_id),
            )

    def _revoked(self) -> bool:
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT revoked FROM approved_roots WHERE root_id = ? AND owner = ? AND domain_id = ?",
                (self._root_id, "owner", self._domain_id),
            ).fetchone()
        return row is not None and row[0] == 1

    def _index(self, relative: str) -> dict[str, str | bool]:
        if self._ignored(relative):
            return {"status": "ignorado", "indexed": False, "missing": "ignore"}
        suffix = Path(relative).suffix.lower()
        if suffix in _REFUSED:
            return {"status": "formato_recusado", "indexed": False, "missing": suffix}
        if suffix not in _ALLOWED:
            return {"status": "formato_recusado", "indexed": False, "missing": suffix or "sem_sufixo"}
        loaded = _read_within_root(self._root, relative)
        if isinstance(loaded, str):
            return {"status": loaded, "indexed": False, "missing": loaded}
        fingerprint = hashlib.sha256(loaded).hexdigest()
        previous = self.fingerprint(relative)
        if previous == fingerprint:
            return {"status": "inalterado", "indexed": False, "missing": ""}
        extracted = _extract(suffix, loaded)
        if extracted is None:
            return {"status": "malformado", "indexed": False, "missing": "formato"}
        excerpt, missing = extracted
        with self._store.transaction() as connection:
            connection.execute(
                """INSERT INTO approved_files(
                       id, owner, domain_id, root_id, relative_path, fingerprint,
                       size, excerpt, missing
                   ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner, domain_id, root_id, relative_path) DO UPDATE SET
                       fingerprint = excluded.fingerprint,
                       size = excluded.size,
                       excerpt = excluded.excerpt,
                       missing = excluded.missing""",
                (
                    secrets.token_hex(16), self._domain_id, self._root_id, relative,
                    fingerprint, len(loaded), excerpt, missing,
                ),
            )
        return {"status": "indexado", "indexed": True, "missing": missing}

    def _ignored(self, relative: str) -> bool:
        if relative == ".jarvisignore" or relative.startswith("."):
            return True
        rules = _ignore_rules(self._root)
        return relative in rules


def _ignore_rules(root: Path) -> set[str]:
    path = root / ".jarvisignore"
    if path.is_symlink() or not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}


def _read_within_root(root: Path, relative: str) -> bytes | str:
    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return "caminho_fora_da_raiz"
    current = root
    if current.is_symlink():
        return "symlink"
    for part in parts:
        current = current / part
        if current.is_symlink():
            return "symlink"
    try:
        if not current.is_file():
            return "ausente"
        size = current.stat().st_size
    except OSError:
        return "leitura_recusada"
    if size > MAX_BYTES:
        return "tamanho"
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(current, flags | nofollow)
    except OSError:
        return "symlink"
    try:
        return os.read(fd, MAX_BYTES + 1)
    except OSError:
        return "leitura_recusada"
    finally:
        os.close(fd)


def _extract(suffix: str, payload: bytes) -> tuple[str, str] | None:
    if b"\x00" in payload:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeError:
        return None
    lowered = text.lower()
    if "<script" in lowered or "javascript:" in lowered:
        return None
    if suffix == ".txt":
        body = text.strip()
        if body == "":
            return "", "vazio"
        return body, ""
    missing: list[str] = []
    kept: list[str] = []
    current_heading = ""
    current_body: list[str] = []

    def flush() -> None:
        if current_heading == "" and not current_body:
            return
        joined = "\n".join(line.strip() for line in current_body if line.strip())
        if joined == "":
            missing.append(current_heading or "secao")
        else:
            kept.append(joined)

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip() or "secao"
            current_body = []
        else:
            current_body.append(line)
    flush()
    return "\n".join(kept), ",".join(missing)
