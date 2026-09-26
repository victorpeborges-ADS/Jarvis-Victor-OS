"""Hash only actually existing local nightly build and screenshot artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPORTS = ROOT / "exports" / "nightly" / "2026-09-26"
APP = ROOT / "apps" / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "macos" / "JARVIS.app"
APK = ROOT / "apps" / "mobile" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path: Path) -> dict:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def app_entry() -> dict:
    if not APP.is_dir():
        return {"status": "NÃO GERADO", "path": str(APP)}
    files = sorted(path for path in APP.rglob("*") if path.is_file())
    values = [dict(relative_path=str(path.relative_to(APP)), **file_entry(path)) for path in files]
    tree = hashlib.sha256()
    for item in values:
        tree.update(f"{item['relative_path']}\0{item['bytes']}\0{item['sha256']}\n".encode())
    return {"status": "GERADO", "path": str(APP), "files": values,
            "total_file_bytes": sum(item["bytes"] for item in values),
            "tree_sha256": tree.hexdigest(), "tree_hash_method": "sha256 of sorted relative_path\\0bytes\\0sha256\\n"}


def main() -> None:
    captures = sorted((EXPORTS / "captures").glob("*.png"))
    document = {
        "date": "2026-09-26", "classification": "synthetic_test_only",
        "macos_app": app_entry(),
        "android_apk": file_entry(APK) if APK.is_file() else {
            "status": "NÃO GERADO", "path": str(APK),
            "reason": "Java Runtime e Android SDK ausentes; assembleDebug exit 1"},
        "captures": [file_entry(path) for path in captures],
        "capture_count": len(captures),
    }
    output = HERE / "EXPORTS_MANIFEST.json"
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{output}: {len(captures)} capturas, app {document['macos_app']['status']}, APK {document['android_apk'].get('status', 'GERADO')}")


if __name__ == "__main__":
    main()
