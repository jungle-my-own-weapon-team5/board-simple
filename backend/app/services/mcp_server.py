from __future__ import annotations

import base64
import html
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ai import ToolLogRecord

SILLOK_SEARCH_URL = "https://sillok.history.go.kr/search/searchResultList.do?keyword={keyword}"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
GENERATED_DIR = STATIC_DIR / "generated"

TOOLS = [
    {
        "name": "history.search_sillok",
        "description": "국사편찬위원회 조선왕조실록 검색 결과를 조회합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "검색할 역사 키워드",
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "image.generate_thumbnail",
        "description": "게시글 제목/본문/카테고리/태그를 분석해 게시글 썸네일 이미지를 생성합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "content", "category"],
        },
    }
]


def handle_json_rpc(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, "Invalid Request")

    method = payload.get("method")
    params = payload.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "history-board-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = _call_tool(db, settings, params)
        else:
            return _error(request_id, -32601, "Method not found")
    except ValueError as exc:
        return _error(request_id, -32602, str(exc))
    except Exception as exc:
        return _error(request_id, -32603, f"Internal error: {exc}")

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _call_tool(db: Session, settings: Settings, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "image.generate_thumbnail":
        return _call_thumbnail_tool(db, settings, arguments)
    if name != "history.search_sillok":
        raise ValueError(f"Unknown tool: {name}")

    keyword = str(arguments.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("keyword is required")

    started = time.perf_counter()
    resources = _search_sillok(keyword)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _save_tool_log(db, name, keyword, "ok", elapsed_ms, f"{len(resources)} resources")

    return {
        "content": [
            {
                "type": "text",
                "text": f"조선왕조실록 검색 결과 {len(resources)}건을 조회했습니다.",
            }
        ],
        "structuredContent": {
            "resources": resources,
            "tool_log": {
                "tool": name,
                "input": keyword,
                "status": "ok",
                "elapsed_ms": elapsed_ms,
            },
        },
        "isError": False,
    }


def generate_thumbnail_for_post(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
) -> dict[str, Any]:
    return _call_thumbnail_tool(
        db,
        settings,
        {
            "title": title,
            "content": content,
            "category": category,
            "tags": tags,
        },
    )


def _call_thumbnail_tool(db: Session, settings: Settings, arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    category = str(arguments.get("category") or "").strip()
    tags = [str(tag).strip() for tag in arguments.get("tags") or [] if str(tag).strip()]
    if not title or not content or not category:
        raise ValueError("title, content, and category are required")

    started = time.perf_counter()
    visual_brief = _make_thumbnail_visual_brief(settings, title, content, category, tags)
    prompt = _build_thumbnail_prompt(title, content, category, tags, visual_brief)
    image_url, status = _generate_thumbnail_image(settings, prompt)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _save_tool_log(db, "image.generate_thumbnail", title, status, elapsed_ms, image_url or "thumbnail_url=null")

    return {
        "content": [
            {
                "type": "text",
                "text": "게시글 내용을 바탕으로 썸네일 이미지를 생성했습니다.",
            }
        ],
        "structuredContent": {
            "image_url": image_url,
            "visual_brief": visual_brief,
            "prompt": prompt,
            "agent_steps": [
                "게시글 제목, 카테고리, 태그, 본문을 읽었습니다.",
                "LLM으로 게시글에 맞는 썸네일 visual brief를 구성했습니다.",
                f"MCP tool image.generate_thumbnail 실행 상태: {status}",
            ],
            "tool_log": {
                "tool": "image.generate_thumbnail",
                "input": title,
                "status": status,
                "elapsed_ms": elapsed_ms,
            },
        },
        "isError": False,
    }


def _make_thumbnail_visual_brief(
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
) -> str:
    fallback = _fallback_visual_brief(title, content, category, tags)
    if not settings.openai_api_key:
        return fallback

    excerpt = _clean_post_excerpt(content)
    tag_text = ", ".join(tags) if tags else "none"
    prompt = (
        "You are an art director and Joseon-era visual researcher for a Korean history community board. "
        "Read the post and create a concise visual brief for a wide 3:2 editorial banner thumbnail. "
        "Return plain text only. Include scene, historically plausible clothing/objects/space, composition, "
        "color/mood, and things to avoid. "
        "Do not invent factual claims. Do not depict identifiable real historical faces. "
        "Avoid readable text, fake Korean lettering, captions, signs, modern logos, and modern objects. "
        "Prefer symbolic objects, spaces, clothing silhouettes, documents, animals, food, books, or palace details. "
        "Use Joseon visual cues carefully: hanbok, official robes, gat, ikseongwan, palace halls, hanji documents, "
        "ink brushes, seals, folding screens, books, wooden floors, and muted natural dyes only when contextually appropriate. "
        "Avoid fantasy crowns, mixed Chinese/Japanese court costumes, theatrical armor, and modern sageuk drama styling.\n"
        f"Title: {title}\nCategory: {category}\nTags: {tag_text}\nPost excerpt: {excerpt}"
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_llm_model,
            input=prompt,
        )
        brief = response.output_text.strip()
        return brief[:1200] if brief else fallback
    except Exception:
        return fallback


def _fallback_visual_brief(title: str, content: str, category: str, tags: list[str]) -> str:
    excerpt = _clean_post_excerpt(content)
    tag_text = ", ".join(tags) if tags else "none"
    return (
        f"Wide 3:2 editorial banner scene concept based on the post title and excerpt. Title: {title}. "
        f"Category: {category}. Tags: {tag_text}. "
        "Use symbolic Joseon-era objects such as palace wooden floors, hanji documents, ink brushes, books, "
        "food trays, maps, seals, folding screens, or architectural details when relevant. "
        "Do not include readable text, fake Korean characters, modern objects, fantasy crowns, or inaccurate court costumes. "
        f"Post excerpt: {excerpt}"
    )


def _build_thumbnail_prompt(
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_brief: str,
) -> str:
    excerpt = _clean_html(content)
    excerpt = re.sub(r"[#>*_~|-]", " ", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()[:700]
    tag_text = ", ".join(tags) if tags else "없음"
    return (
        "Create a polished wide horizontal 3:2 banner thumbnail for a Korean history discussion board, "
        "suitable for a 1536x1024 image. Keep the main subject centered with safe margins so it still works "
        "when cropped in a web card. "
        "Use a historically respectful, non-photorealistic editorial illustration style with warm hanji paper texture, "
        "restrained ink lines, natural mineral colors, and symbolic objects rather than identifiable real historical faces. "
        "For human figures, prefer back views, silhouettes, hands, robes, or partial figures. If clothing appears, "
        "make it plausibly Joseon-era and context-aware: everyday hanbok for common scenes, official robes and gat for officials, "
        "royal robe or ikseongwan only when the post clearly concerns the king or court ceremony. "
        "Do not use fantasy crowns, mixed Chinese/Japanese costumes, modern drama styling, modern props, logos, UI elements, "
        "captions, calligraphy, readable text, pseudo-Korean glyphs, or decorative nonsense letters. "
        "Avoid gore and explicit violence. "
        f"Visual brief: {visual_brief}. "
        f"Title: {title}. Category: {category}. Tags: {tag_text}. Post excerpt: {excerpt}"
    )


def _generate_thumbnail_image(settings: Settings, prompt: str) -> tuple[str | None, str]:
    if not settings.openai_api_key:
        return None, "skipped_no_openai_key"

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.images.generate(
            model=settings.openai_image_model,
            prompt=prompt,
            size=settings.openai_thumbnail_size,
        )
        image = response.data[0]
        filename = f"thumbnail-{uuid4().hex}.png"
        output_path = GENERATED_DIR / filename
        if getattr(image, "b64_json", None):
            output_path.write_bytes(base64.b64decode(image.b64_json))
            return f"/static/generated/{filename}", "ok"
        if getattr(image, "url", None):
            return image.url, "ok"
    except Exception:
        return None, "failed"

    return None, "failed"


def _clean_post_excerpt(content: str) -> str:
    excerpt = _clean_html(content)
    excerpt = re.sub(r"[#>*_~|-]", " ", excerpt)
    return re.sub(r"\s+", " ", excerpt).strip()[:700]


def _search_sillok(keyword: str) -> list[dict[str, str]]:
    url = SILLOK_SEARCH_URL.format(keyword=quote_plus(keyword))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; HistoryBoardMCP/0.1; +local-dev)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        return [
            {
                "title": f"{keyword} 조선왕조실록 검색",
                "provider": "국사편찬위원회 조선왕조실록",
                "url": url,
                "description": f"외부 검색 호출 실패: {exc}. 직접 검색 링크를 제공합니다.",
            }
        ]

    resources = _parse_sillok_search_results(body)
    if resources:
        return resources[:5]
    return [
        {
            "title": f"{keyword} 조선왕조실록 검색",
            "provider": "국사편찬위원회 조선왕조실록",
            "url": url,
            "description": "검색 페이지는 호출했지만 결과 항목을 파싱하지 못했습니다. 직접 검색 링크를 제공합니다.",
        }
    ]


def _parse_sillok_search_results(body: str) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for article_id, title_html in re.findall(r"searchView\('([^']+)'\);\">(.*?)</a>", body, re.S):
        title = _clean_html(title_html)
        if not title:
            continue
        resources.append(
            {
                "title": title,
                "provider": "국사편찬위원회 조선왕조실록",
                "url": f"https://sillok.history.go.kr/id/{article_id}",
                "description": "조선왕조실록 검색 결과에서 조회한 기사입니다.",
            }
        )
    return resources


def _clean_html(value: str) -> str:
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _save_tool_log(
    db: Session,
    tool: str,
    input_text: str,
    status: str,
    elapsed_ms: int,
    result_summary: str,
) -> None:
    try:
        db.add(
            ToolLogRecord(
                tool=tool,
                input_text=input_text,
                status=status,
                elapsed_ms=elapsed_ms,
                result_summary=result_summary,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
