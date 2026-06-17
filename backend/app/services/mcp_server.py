from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import html
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote_plus, urlparse
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ai import ToolLogRecord
from app.services.cache import get_json_cache, make_cache_key, set_json_cache
from app.services.safety import moderate_input, post_safety_message_for

SILLOK_SEARCH_URL = "https://sillok.history.go.kr/search/searchResultList.do?keyword={keyword}"
SILLOK_SEARCH_TIMEOUT_SECONDS = 3
NAVER_SEARCH_TIMEOUT_SECONDS = 4
NAVER_SEARCH_URLS = {
    "encyc": "https://openapi.naver.com/v1/search/encyc.json",
    "webkr": "https://openapi.naver.com/v1/search/webkr.json",
    "news": "https://openapi.naver.com/v1/search/news.json",
    "blog": "https://openapi.naver.com/v1/search/blog.json",
    "book": "https://openapi.naver.com/v1/search/book.json",
}
DEFAULT_NAVER_CATEGORIES = ("encyc", "webkr")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
TRUSTED_HISTORY_DOMAINS = (
    "sillok.history.go.kr",
    "encykorea.aks.ac.kr",
    "db.history.go.kr",
    "contents.history.go.kr",
    "museum.go.kr",
    "kostma.aks.ac.kr",
    "nl.go.kr",
    "riss.kr",
    "scienceon.kisti.re.kr",
)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
GENERATED_DIR = STATIC_DIR / "generated"
JOSEON_NEGATIVE_VISUALS = (
    "kimono, yukata, obi sash, samurai, katana, tatami mats, shoji doors, fusuma screens, "
    "Japanese castle architecture, ukiyo-e composition, anime style, manga style, fantasy crown, "
    "generic Chinese imperial robes, modern sageuk drama styling"
)
MIN_THUMBNAIL_TITLE_CHARS = 6
MIN_THUMBNAIL_CONTENT_CHARS = 80

THUMBNAIL_VARIANTS = [
    "Variant 1: quiet editorial portrait composition with a calm human presence and historically plausible facial expression.",
    "Variant 2: symbolic still-life composition using documents, brushes, books, seals, furniture, or palace objects.",
    "Variant 3: narrative interior scene with Joseon architectural details and restrained human silhouettes.",
]

VISUAL_ROLE_RULES = {
    "royal_non_king": {
        "label": "Joseon royal family member who is not the reigning king",
        "allowed": "samo and danryeong for formal court context, or dopo and gat for restrained noble context; wide hanbok sleeves, correct Korean overlapping collar, waist belt",
        "avoid": "gonryongpo, myeonryugwan, royal crown, emperor costume, dragon robe unless the post clearly says the figure is the reigning king",
        "space": "Joseon palace study, sarangchae-like royal interior, hanji changho windows, low wooden furniture, books, folding screen",
    },
    "king": {
        "label": "Joseon reigning king",
        "allowed": "ikseongwan and gonryongpo only when the scene clearly concerns kingship or court ceremony; otherwise symbolic palace objects are safer",
        "avoid": "fantasy crown, Chinese emperor crown, Japanese court costume, samurai armor",
        "space": "Joseon palace hall, royal study, ilwolobongdo-inspired screen only when contextually appropriate",
    },
    "official": {
        "label": "Joseon civil official or scholar-official",
        "allowed": "samo, danryeong, official belt, scholar robes, gat, documents, brush and ink",
        "avoid": "royal robe, crown, armor unless the post is military",
        "space": "government office, study, wooden desk, hanji documents, book stacks",
    },
    "monk": {
        "label": "Joseon Buddhist monk or Buddhist context",
        "allowed": "plain Korean Buddhist robes, temple objects, sutra scrolls, muted gray and brown cloth",
        "avoid": "Japanese monk robes, ornate fantasy temple costume, samurai monk styling",
        "space": "Korean temple hall, wooden floor, sutra table, mountain temple atmosphere",
    },
    "general": {
        "label": "general Joseon historical topic",
        "allowed": "context-aware hanbok silhouettes, gat, hanji documents, books, maps, brushes, seals, low wooden furniture",
        "avoid": "royal costume unless clearly needed, fantasy armor, Japanese or Chinese costume mixing",
        "space": "Joseon interior with hanji windows, wooden maru or ondol room, folding screen, soban, books",
    },
}

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
        "name": "history.naver_search",
        "description": "네이버 검색 API로 한국어 역사 자료 후보를 조회합니다. 백과/웹문서 결과를 우선 사용합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 역사 키워드나 질문"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(NAVER_SEARCH_URLS.keys())},
                    "description": "검색 카테고리. 기본값은 encyc, webkr입니다.",
                },
                "display": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "history.web_search",
        "description": "범용 웹 검색 API로 역사 자료 후보를 조회하고 신뢰 도메인을 우선 표시합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 역사 키워드나 질문"},
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "결과를 우선 허용할 도메인 목록. 생략하면 역사 신뢰 도메인을 사용합니다.",
                },
                "display": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
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
    if name == "history.search_sillok":
        return _call_sillok_search_tool(db, arguments)
    if name == "history.naver_search":
        return _call_naver_search_tool(db, settings, arguments)
    if name == "history.web_search":
        return _call_web_search_tool(db, settings, arguments)
    raise ValueError(f"Unknown tool: {name}")


def _call_sillok_search_tool(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    keyword = str(arguments.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("keyword is required")

    started = time.perf_counter()
    resources = _search_sillok(keyword)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    status = "ok" if resources else "no_results"
    _save_tool_log(db, "history.search_sillok", keyword, status, elapsed_ms, f"{len(resources)} resources")

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
                "tool": "history.search_sillok",
                "input": keyword,
                "status": status,
                "elapsed_ms": elapsed_ms,
            },
        },
        "isError": False,
    }


def _call_naver_search_tool(db: Session, settings: Settings, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    display = _bounded_display(arguments.get("display"), default=5)
    categories = _normalize_naver_categories(arguments.get("categories"))

    started = time.perf_counter()
    resources, status = _search_naver(settings, query, categories, display)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _save_tool_log(db, "history.naver_search", query, status, elapsed_ms, f"{len(resources)} resources")
    return _search_tool_result(
        "history.naver_search",
        query,
        status,
        elapsed_ms,
        resources,
        f"네이버 검색 결과 {len(resources)}건을 조회했습니다.",
    )


def _call_web_search_tool(db: Session, settings: Settings, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    display = _bounded_display(arguments.get("display"), default=5)
    allowed_domains = _normalize_allowed_domains(arguments.get("allowed_domains"))

    started = time.perf_counter()
    resources, status = _search_web(settings, query, allowed_domains, display)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _save_tool_log(db, "history.web_search", query, status, elapsed_ms, f"{len(resources)} resources")
    return _search_tool_result(
        "history.web_search",
        query,
        status,
        elapsed_ms,
        resources,
        f"웹 검색 결과 {len(resources)}건을 조회했습니다.",
    )


def _search_tool_result(
    tool: str,
    query: str,
    status: str,
    elapsed_ms: int,
    resources: list[dict[str, str]],
    message: str,
) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": message,
            }
        ],
        "structuredContent": {
            "resources": resources,
            "tool_log": {
                "tool": tool,
                "input": query,
                "status": status,
                "elapsed_ms": elapsed_ms,
            },
        },
        "isError": status in {"failed", "not_configured"},
    }


def _bounded_display(value: object, default: int) -> int:
    try:
        return min(max(int(value), 1), 10)
    except (TypeError, ValueError):
        return default


def _normalize_naver_categories(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_NAVER_CATEGORIES)
    categories = [str(item).strip() for item in value]
    normalized = [category for category in categories if category in NAVER_SEARCH_URLS]
    return normalized or list(DEFAULT_NAVER_CATEGORIES)


def _normalize_allowed_domains(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(TRUSTED_HISTORY_DOMAINS)
    domains = [str(item).strip().lower() for item in value if str(item).strip()]
    return domains or list(TRUSTED_HISTORY_DOMAINS)


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


def generate_thumbnail_candidates_for_post(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
    count: int = 3,
) -> list[dict[str, Any]]:
    _raise_if_harmful_thumbnail_request(title, content, tags)
    title, content, category, tags = _validate_thumbnail_arguments(title, content, category, tags)
    safety_message = post_safety_message_for(title, content, tags)
    if safety_message is not None:
        raise ValueError(safety_message)
    visual_profile = _make_thumbnail_visual_profile(title, content, category, tags)
    visual_brief = _make_thumbnail_visual_brief(settings, title, content, category, tags, visual_profile)
    candidate_count = min(max(count, 1), len(THUMBNAIL_VARIANTS))
    cache_key = make_cache_key(
        "thumbnail_candidates:v1",
        {
            "title": title,
            "content": content,
            "category": category,
            "tags": tags,
            "count": candidate_count,
            "image_model": settings.openai_image_model,
            "thumbnail_size": settings.openai_thumbnail_size,
            "visual_profile": visual_profile,
            "visual_brief": visual_brief,
        },
    )
    cached = get_json_cache(settings, cache_key)
    if isinstance(cached, list):
        return [_mark_thumbnail_cache_hit(candidate) for candidate in cached if isinstance(candidate, dict)]

    jobs = [
        (settings, title, content, category, tags, visual_brief, visual_profile, index)
        for index in range(candidate_count)
    ]

    with ThreadPoolExecutor(max_workers=candidate_count) as executor:
        results = list(executor.map(lambda job: _generate_thumbnail_candidate_image(*job), jobs))

    candidates = [_save_thumbnail_candidate_log(db, result) for result in results]
    set_json_cache(settings, cache_key, candidates, settings.thumbnail_cache_ttl_seconds)
    return candidates


def _call_thumbnail_tool(db: Session, settings: Settings, arguments: dict[str, Any]) -> dict[str, Any]:
    raw_title = str(arguments.get("title") or "")
    raw_content = str(arguments.get("content") or "")
    raw_tags = [str(tag) for tag in arguments.get("tags") or []]
    _raise_if_harmful_thumbnail_request(raw_title, raw_content, raw_tags)
    title, content, category, tags = _validate_thumbnail_arguments(
        raw_title,
        raw_content,
        str(arguments.get("category") or ""),
        raw_tags,
    )
    safety_message = post_safety_message_for(title, content, tags)
    if safety_message is not None:
        raise ValueError(safety_message)
    visual_profile = _make_thumbnail_visual_profile(title, content, category, tags)
    visual_brief = _make_thumbnail_visual_brief(settings, title, content, category, tags, visual_profile)
    candidate = _generate_thumbnail_candidate(
        db,
        settings,
        title,
        content,
        category,
        tags,
        visual_brief,
        visual_profile,
        0,
    )

    return {
        "content": [
            {
                "type": "text",
                "text": "게시글 내용을 바탕으로 썸네일 이미지를 생성했습니다.",
            }
        ],
        "structuredContent": candidate,
        "isError": False,
    }


def _raise_if_harmful_thumbnail_request(title: str, content: str, tags: list[str]) -> None:
    text = "\n".join([title, content, " ".join(tags)])
    decision = moderate_input(text, surface="thumbnail", require_history_topic=False)
    if not decision.allowed:
        raise ValueError(decision.message or "썸네일 요청을 처리할 수 없습니다.")


def _validate_thumbnail_arguments(
    title: str,
    content: str,
    category: str,
    tags: list[str],
) -> tuple[str, str, str, list[str]]:
    clean_title = title.strip()
    clean_content = content.strip()
    clean_category = category.strip()
    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not clean_title or not clean_content or not clean_category:
        raise ValueError("title, content, and category are required")
    if len(_plain_thumbnail_text(clean_title)) < MIN_THUMBNAIL_TITLE_CHARS:
        raise ValueError("썸네일을 만들기에는 제목이 너무 빈약합니다. 주제나 인물을 조금 더 구체적으로 적어 주세요.")
    if len(_plain_thumbnail_text(clean_content)) < MIN_THUMBNAIL_CONTENT_CHARS:
        raise ValueError("썸네일을 만들기에는 본문이 너무 빈약합니다. AI가 장면을 잡을 수 있도록 핵심 인물, 사건, 분위기를 더 적어 주세요.")
    return clean_title, clean_content, clean_category, clean_tags


def _plain_thumbnail_text(value: str) -> str:
    text = _clean_html(value)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~|`\\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _generate_thumbnail_candidate(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_brief: str,
    visual_profile: dict[str, str],
    variant_index: int,
) -> dict[str, Any]:
    result = _generate_thumbnail_candidate_image(
        settings,
        title,
        content,
        category,
        tags,
        visual_brief,
        visual_profile,
        variant_index,
    )
    return _save_thumbnail_candidate_log(db, result)


def _generate_thumbnail_candidate_image(
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_brief: str,
    visual_profile: dict[str, str],
    variant_index: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    prompt = _build_thumbnail_prompt(title, content, category, tags, visual_brief, visual_profile, variant_index)
    image_url, status = _generate_thumbnail_image(settings, prompt)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "title": title,
        "image_url": image_url,
        "visual_brief": visual_brief,
        "prompt": prompt,
        "visual_profile": visual_profile,
        "variant_index": variant_index,
        "status": status,
        "elapsed_ms": elapsed_ms,
    }


def _save_thumbnail_candidate_log(db: Session, result: dict[str, Any]) -> dict[str, Any]:
    title = str(result["title"])
    variant_index = int(result["variant_index"])
    image_url = result["image_url"]
    status = str(result["status"])
    elapsed_ms = int(result["elapsed_ms"])
    visual_profile = result["visual_profile"]
    log_input = f"{title} · candidate {variant_index + 1}"
    _save_tool_log(db, "image.generate_thumbnail", log_input, status, elapsed_ms, image_url or "thumbnail_url=null")

    return {
        "image_url": image_url,
        "visual_brief": result["visual_brief"],
        "prompt": result["prompt"],
        "agent_steps": [
            "게시글 제목, 카테고리, 태그, 본문을 읽었습니다.",
            f"인물/장면을 `{visual_profile['role_label']}` 기준으로 분류했습니다.",
            "조선 복식 룰, 공간 키워드, 금지 요소를 프롬프트에 결합했습니다.",
            THUMBNAIL_VARIANTS[variant_index],
            f"MCP tool image.generate_thumbnail 실행 상태: {status}",
        ],
        "tool_log": {
            "tool": "image.generate_thumbnail",
            "input": log_input,
            "status": status,
            "elapsed_ms": elapsed_ms,
        },
    }


def _mark_thumbnail_cache_hit(candidate: dict[str, Any]) -> dict[str, Any]:
    cached_candidate = dict(candidate)
    tool_log = dict(cached_candidate.get("tool_log") or {})
    tool_log["status"] = "cache_hit"
    tool_log["elapsed_ms"] = 0
    cached_candidate["tool_log"] = tool_log
    agent_steps = list(cached_candidate.get("agent_steps") or [])
    if agent_steps:
        agent_steps[-1] = "Redis 캐시에서 기존 썸네일 후보를 불러왔습니다."
    cached_candidate["agent_steps"] = agent_steps
    return cached_candidate


def _make_thumbnail_visual_profile(
    title: str,
    content: str,
    category: str,
    tags: list[str],
) -> dict[str, str]:
    haystack = " ".join([title, category, " ".join(tags), _clean_post_excerpt(content)]).lower()
    if any(term in haystack for term in ["대군", "왕자", "공주", "옹주", "군 "]):
        role = "royal_non_king"
    elif any(term in haystack for term in ["세자", "왕세자"]):
        role = "royal_non_king"
    elif any(term in haystack for term in ["승려", "불교", "사찰", "절 ", "경전"]):
        role = "monk"
    elif any(term in haystack for term in ["문신", "신하", "사림", "관료", "대신", "집현전", "홍문관"]):
        role = "official"
    elif any(term in haystack for term in ["태조", "정종", "태종", "세종", "문종", "단종", "세조", "예종", "성종", "연산군", "중종", "인종", "명종", "선조", "광해군", "인조", "효종", "현종", "숙종", "경종", "영조", "정조", "순조", "헌종", "철종", "고종", "순종", "국왕", "왕 "]):
        role = "king"
    else:
        role = "general"

    rule = VISUAL_ROLE_RULES[role]
    return {
        "role": role,
        "role_label": rule["label"],
        "allowed_clothing": rule["allowed"],
        "forbidden_clothing": rule["avoid"],
        "space_keywords": rule["space"],
        "negative_visuals": JOSEON_NEGATIVE_VISUALS,
    }


def _make_thumbnail_visual_brief(
    settings: Settings,
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_profile: dict[str, str],
) -> str:
    fallback = _fallback_visual_brief(title, content, category, tags, visual_profile)
    if not settings.openai_api_key:
        return fallback

    excerpt = _clean_post_excerpt(content)
    tag_text = ", ".join(tags) if tags else "none"
    prompt = (
        "You are an art director and Joseon-era visual researcher for a Korean history community board. "
        "Read the post and create a concise visual brief for a wide 3:2 editorial banner thumbnail. "
        "Return plain text only. Include scene, historically plausible clothing/objects/space, composition, "
        "color/mood, and things to avoid. "
        "Use the provided visual taxonomy as a hard constraint. If a royal person is not the king, do not dress them as the king. "
        "Do not invent factual claims. Faces are allowed, but treat them as plausible editorial illustration rather than verified portrait reconstruction. "
        "Do not place the post title, captions, signs, or decorative calligraphy in the image. "
        "If the scene naturally includes letters, royal documents, books, or petitions, faint brush strokes or partial document marks are allowed as props, "
        "but they must not become a title design or readable poster text. Avoid fake Korean lettering, modern logos, and modern objects. "
        "Prefer symbolic objects, spaces, clothing silhouettes, documents, animals, food, books, or palace details. "
        "Use Joseon visual cues carefully: hanbok, official robes, gat, ikseongwan, palace halls, hanji documents, "
        "ink brushes, seals, folding screens, books, wooden floors, and muted natural dyes only when contextually appropriate. "
        "Avoid fantasy crowns, mixed Chinese/Japanese court costumes, theatrical armor, and modern sageuk drama styling.\n"
        f"Visual taxonomy: role={visual_profile['role_label']}; allowed clothing={visual_profile['allowed_clothing']}; "
        f"forbidden clothing={visual_profile['forbidden_clothing']}; space cues={visual_profile['space_keywords']}; "
        f"negative visuals={visual_profile['negative_visuals']}.\n"
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


def _fallback_visual_brief(
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_profile: dict[str, str],
) -> str:
    excerpt = _clean_post_excerpt(content)
    tag_text = ", ".join(tags) if tags else "none"
    return (
        f"Wide 3:2 editorial banner scene concept based on the post title and excerpt. Title: {title}. "
        f"Category: {category}. Tags: {tag_text}. "
        f"Visual role: {visual_profile['role_label']}. "
        f"Allowed clothing: {visual_profile['allowed_clothing']}. "
        f"Forbidden clothing: {visual_profile['forbidden_clothing']}. "
        f"Space cues: {visual_profile['space_keywords']}. "
        "Use symbolic Joseon-era objects such as palace wooden floors, hanji documents, ink brushes, books, "
        "food trays, maps, seals, folding screens, or architectural details when relevant. "
        "Do not include the post title, captions, signs, decorative calligraphy, modern objects, fantasy crowns, or inaccurate court costumes. "
        "If documents or letters are part of the scene, use only subtle brush marks as prop detail, not title-like typography. "
        f"Avoid fake Korean characters and {visual_profile['negative_visuals']}. "
        f"Post excerpt: {excerpt}"
    )


def _build_thumbnail_prompt(
    title: str,
    content: str,
    category: str,
    tags: list[str],
    visual_brief: str,
    visual_profile: dict[str, str],
    variant_index: int,
) -> str:
    excerpt = _clean_html(content)
    excerpt = re.sub(r"[#>*_~|-]", " ", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()[:700]
    tag_text = ", ".join(tags) if tags else "없음"
    variant = THUMBNAIL_VARIANTS[variant_index]
    return (
        "Create a polished wide horizontal 3:2 banner thumbnail for a Korean history discussion board, "
        "suitable for a 1536x1024 image. Keep the main subject centered with safe margins so it still works "
        "when cropped in a web card. "
        "Use a historically respectful, non-photorealistic editorial illustration style with warm hanji paper texture, "
        "restrained ink lines, natural mineral colors, and historically plausible human figures. "
        "For human figures, faces may be visible; keep expressions calm, respectful, and editorial rather than photorealistic portrait claims. "
        f"Visual taxonomy role: {visual_profile['role_label']}. "
        f"Allowed clothing and props: {visual_profile['allowed_clothing']}. "
        f"Forbidden clothing and props: {visual_profile['forbidden_clothing']}. "
        f"Joseon space cues: {visual_profile['space_keywords']}. "
        f"Strictly avoid Japanese visual language and style: {visual_profile['negative_visuals']}. "
        "Do not use modern props, logos, UI elements, captions, title calligraphy, poster text, pseudo-Korean glyphs, or decorative nonsense letters. "
        "When letters, petitions, books, or royal documents are part of the described scene, allow subtle ink strokes or partial document marks as background prop texture only; "
        "do not write the post title or summarize the post as visible calligraphy. "
        "Avoid gore and explicit violence. "
        f"{variant} "
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
        with urllib.request.urlopen(request, timeout=SILLOK_SEARCH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError):
        return []

    resources = _parse_sillok_search_results(body)
    if resources:
        return resources[:5]
    return []


def _search_naver(
    settings: Settings,
    query: str,
    categories: list[str],
    display: int,
) -> tuple[list[dict[str, str]], str]:
    if not settings.naver_client_id or not settings.naver_client_secret:
        return [], "not_configured"

    resources: list[dict[str, str]] = []
    for category in categories:
        endpoint = NAVER_SEARCH_URLS[category]
        params = urlencode({"query": query, "display": display, "start": 1, "sort": "sim"})
        request = urllib.request.Request(
            f"{endpoint}?{params}",
            headers={
                "X-Naver-Client-Id": settings.naver_client_id,
                "X-Naver-Client-Secret": settings.naver_client_secret,
                "User-Agent": "HistoryBoardMCP/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=NAVER_SEARCH_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError):
            continue
        resources.extend(_parse_naver_search_results(body, category))

    unique_resources = _dedupe_resources(resources)
    if unique_resources:
        return unique_resources[:display], "ok"
    return [], "no_results"


def _parse_naver_search_results(body: str, category: str) -> list[dict[str, str]]:
    try:
        import json

        payload = json.loads(body)
    except Exception:
        return []

    resources: list[dict[str, str]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        title = _clean_html(str(item.get("title") or ""))
        url = _clean_html(str(item.get("link") or ""))
        description = _clean_html(str(item.get("description") or ""))
        if not title or not url:
            continue
        resources.append(
            {
                "title": title,
                "provider": f"네이버 검색/{category}",
                "url": url,
                "description": description or "네이버 검색 API에서 조회한 자료 후보입니다.",
            }
        )
    return resources


def _search_web(
    settings: Settings,
    query: str,
    allowed_domains: list[str],
    display: int,
) -> tuple[list[dict[str, str]], str]:
    if not settings.brave_search_api_key:
        return [], "not_configured"

    params = urlencode({"q": _with_history_domain_hints(query, allowed_domains), "count": display})
    request = urllib.request.Request(
        f"{BRAVE_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_search_api_key,
            "User-Agent": "HistoryBoardMCP/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError):
        return [], "failed"

    resources = _rank_web_resources(_parse_brave_search_results(body), allowed_domains)
    if resources:
        return resources[:display], "ok"
    return [], "no_results"


def _with_history_domain_hints(query: str, allowed_domains: list[str]) -> str:
    domain_query = " OR ".join(f"site:{domain}" for domain in allowed_domains[:5])
    return f"{query} ({domain_query})" if domain_query else query


def _parse_brave_search_results(body: str) -> list[dict[str, str]]:
    try:
        import json

        payload = json.loads(body)
    except Exception:
        return []

    resources: list[dict[str, str]] = []
    for item in ((payload.get("web") or {}).get("results") or []):
        if not isinstance(item, dict):
            continue
        title = _clean_html(str(item.get("title") or ""))
        url = str(item.get("url") or "").strip()
        description = _clean_html(str(item.get("description") or ""))
        if not title or not url:
            continue
        resources.append(
            {
                "title": title,
                "provider": "Brave Search",
                "url": url,
                "description": description or "범용 웹 검색 API에서 조회한 자료 후보입니다.",
            }
        )
    return resources


def _rank_web_resources(resources: list[dict[str, str]], allowed_domains: list[str]) -> list[dict[str, str]]:
    return sorted(
        _dedupe_resources(resources),
        key=lambda resource: (
            0 if _is_allowed_domain(resource["url"], allowed_domains) else 1,
            resource["title"],
        ),
    )


def _is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _dedupe_resources(resources: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for resource in resources:
        url = resource.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(resource)
    return unique


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
