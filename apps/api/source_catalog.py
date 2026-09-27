"""Versioned server-owned catalog for synthetic source admission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

CATALOG_PATH = Path(__file__).resolve().parent / "fixtures" / "selected_sources.v1.json"
_raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
CATALOG_ID = _raw["catalog_id"]
CATALOG_VERSION = _raw["catalog_version"]
_items: dict[str, dict] = {}
for _item in _raw["items"]:
    _content = _item["content"]
    _digest = hashlib.sha256(_content.encode("utf-8")).hexdigest()
    _expected_provenance = {
        "kind": "curated_server_fixture",
        "catalog_id": CATALOG_ID,
        "catalog_version": CATALOG_VERSION,
        "fixture_id": _item["id"],
        "note": "Conteúdo de demonstração criado para testes locais; não representa fonte externa.",
    }
    if (
        _item["id"] in _items
        or _item["classification"] != "synthetic_verified"
        or _item["content_sha256"] != _digest
        or _item["provenance"] != _expected_provenance
        or "\x00" in _content
        or not 1 <= len(_content.encode("utf-8")) <= 50000
    ):
        raise RuntimeError("catálogo local de fixtures inválido")
    _items[_item["id"]] = MappingProxyType(dict(_item))
FIXTURES = MappingProxyType(_items)


def fixture_for(fixture_id: str) -> dict | None:
    item = FIXTURES.get(fixture_id)
    return dict(item) if item is not None else None


def public_fixtures() -> list[dict]:
    return [{key: value for key, value in item.items() if key != "content"}
            for item in FIXTURES.values()]
