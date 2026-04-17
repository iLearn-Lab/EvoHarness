from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


PROTOCOL_VERSION = "2025-06-18"
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_COM_SUPPORT: bool | None = None


def _workspace_root() -> Path:
    configured = os.environ.get("EVO_HARNESS_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _resolve_path(path_text: str) -> Path:
    raw = Path(path_text)
    if raw.is_absolute():
        return raw
    return (_workspace_root() / raw).resolve()


def _supports_word_automation() -> bool:
    global _WORD_COM_SUPPORT
    if _WORD_COM_SUPPORT is not None:
        return _WORD_COM_SUPPORT
    command = (
        "$word = New-Object -ComObject Word.Application; "
        "$word.Visible = $false; "
        "$word.Quit(); "
        "Write-Output 'ok'"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except Exception:
        _WORD_COM_SUPPORT = False
        return _WORD_COM_SUPPORT
    _WORD_COM_SUPPORT = completed.returncode == 0
    return _WORD_COM_SUPPORT


def _inspect_document_support() -> dict[str, Any]:
    word_com = _supports_word_automation()
    notes = [
        "`.docx` read and write are available through the built-in document package reader/writer.",
        "Prefer `.docx` outputs for repeatable automation and validation.",
    ]
    if word_com:
        notes.append("Legacy `.doc` read is available through local Word COM automation.")
    else:
        notes.append("Legacy `.doc` read is best-effort only; convert to `.docx` or install Microsoft Word for COM automation.")
    return {
        "workspace": str(_workspace_root()),
        "docx_read": True,
        "docx_write": True,
        "doc_read_via_word_com": word_com,
        "recommended_output_extension": ".docx",
        "notes": notes,
    }


def _read_document_text(path_text: str) -> dict[str, Any]:
    path = _resolve_path(path_text)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = _read_docx_text(path)
    elif suffix == ".doc":
        if not _supports_word_automation():
            raise ValueError(
                "Legacy .doc extraction is unavailable because Word COM automation is not present. "
                "Convert the file to .docx or install Microsoft Word."
            )
        text = _read_doc_via_word(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "suffix": suffix or "(no suffix)",
        "char_count": len(text),
        "text": text,
    }


def _write_report_docx(arguments: dict[str, Any]) -> dict[str, Any]:
    requested_path = str(arguments.get("path", "")).strip()
    if not requested_path:
        raise ValueError("`path` is required.")
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ValueError("`title` is required.")

    path = _resolve_path(requested_path)
    if path.suffix.lower() != ".docx":
        path = path.with_suffix(".docx")
    if path.exists() and not bool(arguments.get("overwrite", False)):
        raise FileExistsError(f"Destination already exists: {path}")

    sections = _normalize_sections(arguments.get("sections", []))
    body = str(arguments.get("body", "")).strip()
    if body and not sections:
        sections = [{"heading": "正文", "paragraphs": [body]}]
    if not sections:
        raise ValueError("Provide `sections` or `body` so the report has content.")

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_minimal_docx(path, title=title, sections=sections)
    return {
        "path": str(path),
        "title": title,
        "section_count": len(sections),
        "char_count": sum(len(paragraph) for section in sections for paragraph in section["paragraphs"]),
    }


def _normalize_sections(raw_sections: Any) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    if not isinstance(raw_sections, list):
        return sections
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading", "")).strip()
        paragraphs_raw = item.get("paragraphs", [])
        bullets_raw = item.get("bullets", [])
        if isinstance(paragraphs_raw, str):
            paragraphs_raw = [paragraphs_raw]
        if isinstance(bullets_raw, str):
            bullets_raw = [bullets_raw]
        paragraphs = [str(text).strip() for text in paragraphs_raw if str(text).strip()]
        paragraphs.extend(f"- {str(text).strip()}" for text in bullets_raw if str(text).strip())
        if heading or paragraphs:
            sections.append({"heading": heading, "paragraphs": paragraphs})
    return sections


def _read_docx_text(path: Path) -> str:
    namespace = {"w": _WORD_NS}
    with zipfile.ZipFile(path, "r") as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:body/w:p", namespace):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()


def _read_doc_via_word(path: Path) -> str:
    quoted_path = str(path).replace("'", "''")
    command = "\n".join(
        [
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
            "$word = New-Object -ComObject Word.Application",
            "$word.Visible = $false",
            f"$doc = $word.Documents.Open('{quoted_path}', $false, $true)",
            "try {",
            "  $doc.Content.Text | Write-Output",
            "} finally {",
            "  $doc.Close($false)",
            "  $word.Quit()",
            "}",
        ]
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Unknown Word automation failure."
        raise ValueError(stderr)
    return completed.stdout.strip()


def _write_minimal_docx(path: Path, *, title: str, sections: list[dict[str, Any]]) -> None:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    paragraphs = [_docx_paragraph(title)]
    for section in sections:
        heading = str(section.get("heading", "")).strip()
        if heading:
            paragraphs.append(_docx_paragraph(heading))
        for paragraph in section.get("paragraphs", []):
            paragraphs.append(_docx_paragraph(str(paragraph)))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"{''.join(paragraphs)}"
        "<w:sectPr>"
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<dc:creator>Evo Harness</dc:creator>"
        "<cp:lastModifiedBy>Evo Harness</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created_at}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Evo Harness</Application>"
        "</Properties>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", relationships_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("word/document.xml", document_xml)


def _docx_paragraph(text: str) -> str:
    return (
        "<w:p>"
        "<w:r>"
        f'<w:t xml:space="preserve">{escape(text)}</w:t>'
        "</w:r>"
        "</w:p>"
    )


def _prompt_for_lab_report(arguments: dict[str, Any]) -> str:
    assignment = str(arguments.get("assignment", "")).strip() or "the current lab assignment"
    output_path = str(arguments.get("output_path", "")).strip() or "report.docx"
    return (
        f"Draft a structured lab report for {assignment}.\n"
        "- Use sections for objective, materials, steps, results, analysis, and conclusion.\n"
        "- Keep the language clear and ready to write into a .docx file.\n"
        f"- Target output path: {output_path}\n"
        "- If the source brief is incomplete, state the assumptions before drafting."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "document-automation", "version": "0.1.0"},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "inspect_document_support",
                    "description": "Describe available `.doc` and `.docx` automation support for this workspace.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                },
                {
                    "name": "read_document_text",
                    "description": "Read text from a `.docx` file or attempt best-effort `.doc` extraction when Word automation is available.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "write_report_docx",
                    "description": "Write a structured report to a `.docx` file without requiring an external Python dependency.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "overwrite": {"type": "boolean"},
                            "sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "heading": {"type": "string"},
                                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                                        "bullets": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["path", "title"],
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments", {}) or {})
        if name == "inspect_document_support":
            payload = _inspect_document_support()
        elif name == "read_document_text":
            payload = _read_document_text(str(arguments.get("path", "")))
        elif name == "write_report_docx":
            payload = _write_report_docx(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
            "metadata": {"workspace": str(_workspace_root()), "tool": name},
        }
    if method == "resources/list":
        return {"resources": []}
    if method == "resources/read":
        raise ValueError("This server does not expose MCP resources.")
    if method == "prompts/list":
        return {
            "prompts": [
                {
                    "name": "draft_lab_report",
                    "description": "Turn an assignment brief into a structured lab report outline.",
                    "arguments": [
                        {"name": "assignment", "description": "Assignment topic or source document path.", "required": False},
                        {"name": "output_path", "description": "Target `.docx` output path.", "required": False},
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "draft_lab_report":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Lab report drafting prompt",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _prompt_for_lab_report(arguments)}],
                }
            ],
        }
    if method == "notifications/initialized":
        return {}
    raise ValueError(f"Unsupported MCP method: {method}")


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        message = _read_message()
        if message is None:
            return
        method = str(message.get("method", ""))
        request_id = message.get("id")
        try:
            result = _handle_method(method, dict(message.get("params", {}) or {}))
            if request_id is not None:
                _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if request_id is not None:
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


if __name__ == "__main__":
    main()
