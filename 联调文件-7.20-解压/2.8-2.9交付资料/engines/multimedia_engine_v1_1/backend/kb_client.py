from __future__ import annotations

from html import escape
from typing import Any
import json
import urllib.error
import urllib.request


def post_json(url: str, payload: dict[str, Any], timeout: int = 15) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"知识库接口 HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"知识库接口不可用：{exc.reason}") from exc


def get_task_materials(kb_base: str, actor_id: str, task_type: str, query: str, top_k: int) -> dict[str, Any]:
    return post_json(
        kb_base.rstrip("/") + "/api/kb/task-materials",
        {
            "actor_id": actor_id,
            "task_type": task_type,
            "query": query,
            "top_k": top_k,
            "include_templates": True,
        },
    )


def render_xml_context(material_package: dict[str, Any]) -> dict[str, Any]:
    materials = material_package.get("materials", [])
    doc_lines = ["<documents>"]
    context_lines: list[str] = []
    references: list[dict[str, str]] = []
    for index, item in enumerate(materials, start=1):
        context_id = str(index)
        document_id = item.get("material_id", f"DOC-{index}")
        title = item.get("title", "")
        summary = item.get("summary", "")
        content = item.get("content") or summary
        citation = item.get("citation", "")
        source = item.get("source", "")
        version = item.get("version", "")
        item_type = item.get("type", "")
        references.append(
            {
                "context_id": context_id,
                "document_id": document_id,
                "title": title,
                "citation": citation,
                "source": source,
                "version": version,
                "type": item_type,
            }
        )
        doc_lines.extend(
            [
                f'  <document id="{escape(context_id)}" document_id="{escape(document_id)}">',
                f"    <title>{escape(title)}</title>",
                f"    <description>{escape(summary)}</description>",
                f"    <source>{escape(source)}</source>",
                f"    <citation>{escape(citation)}</citation>",
                "  </document>",
            ]
        )
        context_lines.append(f'<context id="{escape(context_id)}" document_id="{escape(document_id)}">')
        context_lines.append(escape(content))
        if item_type == "media_asset":
            url = _extract_asset_url(content)
            context_lines.extend(
                [
                    f'<image url="{escape(url)}">',
                    f"  <image_caption>{escape(title)}</image_caption>",
                    f"  <image_ocr>{escape(summary)}</image_ocr>",
                    "</image>",
                ]
            )
        context_lines.append("</context>")
        context_lines.append("")
    doc_lines.append("</documents>")
    xml = "\n".join(doc_lines + [""] + context_lines).strip()
    return {"xml_context": xml, "references": references}


def _extract_asset_url(content: str) -> str:
    marker = "文件路径："
    if marker in content:
        return content.split(marker, 1)[1].split("。", 1)[0].strip()
    return "local://asset-not-specified"
