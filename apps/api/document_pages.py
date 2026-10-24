"""Documento estruturado. O número da página aponta para a origem.

Markdown, HTML e PDF simples vêm antes de DOCX, XLSX e PPTX. Esses três
formatos de escritório são recusados. O HTML não carrega script.
"""

from __future__ import annotations

from html import escape


def render_markdown(pages: tuple[tuple[int, str, str], ...]) -> str:
    blocks = []
    for number, source_id, text in pages:
        blocks.append(f"## {number}. {escape_plain(text)}\n\nOrigem: {source_id}")
    return "\n\n".join(blocks)


def render_html(pages: tuple[tuple[int, str, str], ...]) -> str:
    parts = ["<!DOCTYPE html>", "<html>", "<body>"]
    for number, source_id, text in pages:
        parts.append(
            f"<section><h2>{number}</h2><p>{escape(text)}</p>"
            f"<p>Origem: {escape(source_id)}</p></section>"
        )
    parts.extend(["</body>", "</html>"])
    document = "\n".join(parts)
    if "<script" in document.lower():
        raise ValueError("documento recusado")
    return document


def render_pdf(pages: tuple[tuple[int, str, str], ...]) -> bytes:
    lines = [f"pagina {number} origem {source_id}" for number, source_id, _text in pages]
    stream = "\n".join(lines).encode("latin-1", "replace")
    return (
        b"%PDF-1.1\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj\n"
        + f"4 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
        + stream
        + b"\nendstream endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF\n"
    )


def render(kind: str, pages: tuple[tuple[int, str, str], ...]) -> str | bytes:
    if kind == "markdown":
        return render_markdown(pages)
    if kind == "html":
        return render_html(pages)
    if kind == "pdf":
        return render_pdf(pages)
    raise ValueError("documento recusado")


def origin_matches(kind: str, body: str | bytes, pages: tuple[tuple[int, str, str], ...]) -> bool:
    text = body.decode("latin-1") if isinstance(body, bytes) else body
    return all(f"{number}" in text and source_id in text and f"Origem: {source_id}" in text or (
        kind == "pdf" and f"pagina {number} origem {source_id}" in text
    ) for number, source_id, _text in pages)


def escape_plain(value: str) -> str:
    return value.replace("\x00", "")
