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
from urllib.parse import quote_plus
from urllib.parse import urljoin
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ai import ToolLogRecord
from app.services.cache import get_json_cache, make_cache_key, set_json_cache
from app.services.safety import moderate_input, post_safety_message_for

SILLOK_SEARCH_URL = "https://sillok.history.go.kr/search/searchResultList.do?topSearchWord={keyword}&pageUnit=10"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
GENERATED_DIR = STATIC_DIR / "generated"
ENCYKOREA_SEED_DIR = Path(__file__).resolve().parents[2] / "rag_seed" / "overview" / "encykorea"
USER_AGENT = "Mozilla/5.0 (compatible; HistoryBoardMCP/0.1; +local-dev)"
WEB_WHITELIST_SEARCHES = [
    (
        "한국역사정보통합시스템",
        "web_reference",
        "https://www.koreanhistory.or.kr/search/searchResult.do?searchWord={keyword}",
    ),
    (
        "우리역사넷",
        "web_reference",
        "https://contents.history.go.kr/front/search/search.do?keyword={keyword}",
    ),
    (
        "국가유산포털",
        "web_reference",
        "https://www.heritage.go.kr/heri/cul/culSelectViewList.do?searchCondition={keyword}",
    ),
]
JOSEON_NEGATIVE_VISUALS = (
    "kimono, yukata, obi sash, samurai, katana, tatami mats, shoji doors, fusuma screens, "
    "Japanese castle architecture, ukiyo-e composition, anime style, manga style, fantasy crown, "
    "generic Chinese imperial robes, modern sageuk drama styling"
)
MIN_THUMBNAIL_TITLE_CHARS = 6
MIN_THUMBNAIL_CONTENT_CHARS = 80
THUMBNAIL_PROMPT_VERSION = "thumbnail-v4"
KING_NAMES = [
    "태조",
    "정종",
    "태종",
    "세종",
    "문종",
    "단종",
    "세조",
    "예종",
    "성종",
    "연산군",
    "중종",
    "인종",
    "명종",
    "선조",
    "광해군",
    "인조",
    "효종",
    "현종",
    "숙종",
    "경종",
    "영조",
    "정조",
    "순조",
    "헌종",
    "철종",
    "고종",
    "순종",
    "양녕대군",
    "효령대군",
    "충녕대군",
]

THUMBNAIL_VARIANTS = [
    "Variant 1: half-length or seated human portrait scene with one or two prominent figures, historically plausible facial expression, and Joseon court painting restraint.",
    "Variant 2: symbolic still-life composition using documents, brushes, books, seals, furniture, or palace objects.",
    "Variant 3: narrative interior scene with Joseon architectural details and mid-sized human figures interacting with documents, books, or court objects.",
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

VISUAL_PLACE_RULES = [
    {
        "label": "palace or royal interior",
        "terms": ["궁궐", "궁중", "왕실", "대전", "편전", "어전", "행궁", "궐내", "왕의 공간"],
        "cues": "palace hall, royal study, polished wooden floor, hanji doors, folding screen, low court furniture",
    },
    {
        "label": "scholarly study or archive",
        "terms": ["집현전", "홍문관", "규장각", "서고", "책", "문서", "어찰", "편지", "서찰", "기록", "사료"],
        "cues": "scholar study, archive shelves, stacked books, hanji documents, inkstone, brushes, document boxes",
    },
    {
        "label": "government office",
        "terms": ["관아", "의정부", "육조", "관청", "공문서", "상소", "정무", "관리", "관료"],
        "cues": "Joseon government office, desks with petitions, seals, scroll trays, officials seated in discussion",
    },
    {
        "label": "temple or mountain monastery",
        "terms": ["사찰", "절", "불교", "승려", "경전", "탑", "법당"],
        "cues": "Korean temple hall, mountain temple courtyard, sutra table, wooden columns, muted cloth and wood",
    },
    {
        "label": "battlefield or military camp",
        "terms": ["전쟁", "전투", "왜란", "호란", "의병", "장군", "군영", "진영", "성곽", "무기"],
        "cues": "restrained battlefield map table, fortress wall, military camp, banners, armor kept understated",
    },
    {
        "label": "port or diplomacy route",
        "terms": ["외교", "사신", "통신사", "대마도", "명나라", "청나라", "일본", "항구", "바다", "선박"],
        "cues": "diplomatic reception space, port map, travel chest, ship silhouette, sealed letters, route map",
    },
    {
        "label": "village or everyday life space",
        "terms": ["생활", "장터", "시장", "마을", "백성", "농사", "음식", "식생활", "민가"],
        "cues": "Joseon village lane, market stall, modest hanok interior, soban, baskets, everyday tools",
    },
    {
        "label": "ritual or tomb setting",
        "terms": ["제사", "국장", "장례", "무덤", "능", "묘", "종묘", "의례", "제향"],
        "cues": "ritual table, ancestral tablets, subdued ceremonial space, tomb path, offering vessels",
    },
]

VISUAL_PROP_RULES = [
    {
        "terms": ["어찰", "편지", "서찰", "문서", "상소", "교지", "실록", "사료", "기록"],
        "cues": "hanji letters, royal documents, petitions, document tubes, red seals, ink brush marks as props only",
    },
    {
        "terms": ["책", "경전", "학문", "집현전", "홍문관", "규장각", "훈민정음", "문자"],
        "cues": "bound books, woodblock print pages, brush, inkstone, book stacks, scholar desk",
    },
    {
        "terms": ["지도", "외교", "사신", "전쟁", "행군", "대마도", "국경"],
        "cues": "hand-drawn map, route marks, compass-like measuring tools, travel documents, sealed dispatches",
    },
    {
        "terms": ["인장", "옥새", "도장", "교지", "왕명", "임명"],
        "cues": "seal box, red seal impression, folded royal decree, lacquered document tray",
    },
    {
        "terms": ["음식", "식생활", "밥", "술", "차", "약", "의학", "병환", "건강"],
        "cues": "soban table, ceramic bowls, brassware, medicine packets, tea cups, herb bundles",
    },
    {
        "terms": ["고양이", "개", "말", "매", "동물"],
        "cues": "small historically plausible animal as a subtle narrative prop, not a cute modern mascot",
    },
    {
        "terms": ["칼", "활", "창", "갑옷", "무기", "전투", "장군"],
        "cues": "sheathed sword, bow, quiver, armor stand, military banner, avoid explicit violence",
    },
]

VISUAL_MOOD_RULES = [
    {
        "terms": ["논쟁", "갈등", "반정", "폐위", "숙청", "역모", "유배", "처벌"],
        "cues": "tense but restrained mood, divided composition, low contrast shadows, no melodrama",
    },
    {
        "terms": ["토론", "질문", "해석", "평가", "논의"],
        "cues": "thoughtful discussion mood, balanced composition, quiet scholarly tension",
    },
    {
        "terms": ["생활", "문화", "음식", "일상", "풍습"],
        "cues": "warm everyday mood, muted natural dyes, tactile objects, human-scale scene",
    },
    {
        "terms": ["전쟁", "왜란", "호란", "의병", "전투"],
        "cues": "somber historical gravity, dust-muted palette, strategic rather than violent framing",
    },
]

TOOLS = [
    {
        "name": "history.search",
        "description": "여러 한국사 자료 provider를 묶어 검색합니다. provider는 auto, sillok, encykorea, museum, kostma, nlk, web 중 선택할 수 있습니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "검색할 역사 키워드",
                },
                "providers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["auto", "sillok", "encykorea", "museum", "kostma", "nlk", "web"],
                    },
                    "description": "검색 provider 목록입니다. 생략하면 auto 라우팅을 사용합니다.",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "history.search_sillok",
        "description": "Deprecated. 새 호출은 history.search with providers=[\"sillok\"]를 사용하세요. 국사편찬위원회 조선왕조실록 검색 결과를 조회합니다.",
        "deprecated": True,
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
    if name == "history.search":
        return _call_history_search_tool(db, arguments)
    if name != "history.search_sillok":
        raise ValueError(f"Unknown tool: {name}")

    keyword = str(arguments.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("keyword is required")

    started = time.perf_counter()
    resources = _search_sillok(keyword)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    status = "ok" if resources else "no_results"
    _save_tool_log(db, name, keyword, status, elapsed_ms, f"{len(resources)} resources")

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
                "status": status,
                "elapsed_ms": elapsed_ms,
            },
        },
        "isError": False,
    }


def _call_history_search_tool(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    keyword = str(arguments.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("keyword is required")
    providers = [str(provider) for provider in arguments.get("providers") or ["auto"]]
    started = time.perf_counter()
    resources = search_history_providers(keyword, providers)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    verified_count = sum(1 for item in resources if item.get("result_type") == "verified")
    link_count = sum(1 for item in resources if item.get("result_type") == "search_link")
    status = "ok" if verified_count else "link_ready" if link_count else "no_results"
    provider_names = ", ".join(_resolve_history_providers(keyword, providers))
    _save_tool_log(
        db,
        "history.search",
        f"{keyword} · providers={provider_names}",
        status,
        elapsed_ms,
        f"{verified_count} verified resources, {link_count} search links",
    )
    return {
        "content": [
            {
                "type": "text",
                "text": f"한국사 자료 provider {provider_names}에서 {len(resources)}건을 조회했습니다.",
            }
        ],
        "structuredContent": {
            "resources": resources,
            "tool_log": {
                "tool": "history.search",
                "input": keyword,
                "status": status,
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
    candidate_count = min(max(count, 1), len(THUMBNAIL_VARIANTS))
    cache_key = make_cache_key(
        "thumbnail_candidates:v2",
        {
            "title": title,
            "content": content,
            "category": category,
            "tags": sorted(tags),
            "count": candidate_count,
            "image_model": settings.openai_image_model,
            "thumbnail_size": settings.openai_thumbnail_size,
            "prompt_version": THUMBNAIL_PROMPT_VERSION,
        },
    )
    cached = get_json_cache(settings, cache_key)
    if isinstance(cached, list):
        return [_mark_thumbnail_cache_hit(candidate) for candidate in cached if isinstance(candidate, dict)]

    visual_profile = _make_thumbnail_visual_profile(title, content, category, tags)
    visual_brief = _make_thumbnail_visual_brief(settings, title, content, category, tags, visual_profile)

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
            f"장소는 `{visual_profile['place_label']}`, 핵심 소품은 `{visual_profile['prop_keywords']}`로 잡았습니다.",
            "조선 복식 룰, 장소/소품 키워드, 금지 요소를 프롬프트에 결합했습니다.",
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
    elif any(term in haystack for term in ["태조", "정종", "태종", "세종", "문종", "단종", "세조", "예종", "성종", "연산군", "중종", "인종", "명종", "선조", "광해군", "인조", "효종", "현종", "숙종", "경종", "영조", "정조", "순조", "헌종", "철종", "고종", "순종", "국왕", "왕 "]):
        role = "king"
    elif any(term in haystack for term in ["문신", "신하", "사림", "관료", "대신", "집현전", "홍문관"]):
        role = "official"
    else:
        role = "general"

    rule = VISUAL_ROLE_RULES[role]
    place = _first_matching_visual_rule(haystack, VISUAL_PLACE_RULES)
    prop_cues = _matching_visual_cues(haystack, VISUAL_PROP_RULES, limit=3)
    mood_cues = _matching_visual_cues(haystack, VISUAL_MOOD_RULES, limit=2)
    if place is None:
        place = {
            "label": "context-aware Joseon interior or exterior",
            "cues": "context-aware Joseon setting, hanji windows, wooden floor, folding screen, books, everyday objects",
        }
    if not prop_cues:
        prop_cues = ["context-aware Joseon objects such as books, documents, brushes, maps, seals, low furniture, or vessels"]
    if not mood_cues:
        mood_cues = ["calm historical editorial mood, restrained composition, muted natural colors"]

    return {
        "role": role,
        "role_label": rule["label"],
        "allowed_clothing": rule["allowed"],
        "forbidden_clothing": rule["avoid"],
        "place_label": str(place["label"]),
        "space_keywords": _join_visual_cues([rule["space"], str(place["cues"])]),
        "prop_keywords": _join_visual_cues(prop_cues),
        "mood_keywords": _join_visual_cues(mood_cues),
        "negative_visuals": JOSEON_NEGATIVE_VISUALS,
    }


def _first_matching_visual_rule(haystack: str, rules: list[dict[str, object]]) -> dict[str, object] | None:
    for rule in rules:
        terms = [str(term).lower() for term in rule.get("terms", [])]
        if any(term in haystack for term in terms):
            return rule
    return None


def _matching_visual_cues(haystack: str, rules: list[dict[str, object]], limit: int) -> list[str]:
    matches = []
    for rule in rules:
        terms = [str(term).lower() for term in rule.get("terms", [])]
        if any(term in haystack for term in terms):
            matches.append(str(rule["cues"]))
        if len(matches) >= limit:
            break
    return matches


def _join_visual_cues(cues: list[str]) -> str:
    seen: set[str] = set()
    unique = []
    for cue in cues:
        normalized = cue.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return "; ".join(unique)


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
        "The default art direction is Joseon court documentary painting adapted for an editorial web thumbnail: "
        "aged hanji paper, fine ink outlines, faded mineral pigments, calm flat perspective, and restrained palace-record mood. "
        "Human figures do not need to be tiny; when the post centers on people, describe half-length, seated, or medium-close figures "
        "with refined Joseon portrait-like restraint, soft faces, correct clothing, and historically plausible posture. "
        "Use the provided visual taxonomy as a hard constraint. If a royal person is not the king, do not dress them as the king. "
        "Do not invent factual claims. Faces are allowed, but treat them as plausible editorial illustration rather than verified portrait reconstruction. "
        "Do not place the post title, captions, signs, or decorative calligraphy in the image. "
        "If the scene naturally includes letters, royal documents, books, or petitions, faint brush strokes or partial document marks are allowed as props, "
        "but they must not become a title design or readable poster text. Avoid fake Korean lettering, modern logos, and modern objects. "
        "Prefer symbolic objects, spaces, clothing silhouettes, documents, animals, food, books, or palace details. "
        "Use Joseon visual cues carefully: hanbok, jeogori and chima, official robes, gat, ikseongwan, palace halls, hanji documents, "
        "ink brushes, seals, folding screens, books, wooden floors, carved wooden furniture, and muted natural dyes only when contextually appropriate. "
        "Avoid fantasy crowns, mixed Chinese/Japanese court costumes, theatrical armor, modern sageuk drama styling, anime, manga, and glossy digital cartoon rendering.\n"
        f"Visual taxonomy: role={visual_profile['role_label']}; allowed clothing={visual_profile['allowed_clothing']}; "
        f"forbidden clothing={visual_profile['forbidden_clothing']}; place={visual_profile['place_label']}; "
        f"space cues={visual_profile['space_keywords']}; prop cues={visual_profile['prop_keywords']}; "
        f"mood cues={visual_profile['mood_keywords']}; "
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
        f"Place: {visual_profile['place_label']}. "
        f"Space cues: {visual_profile['space_keywords']}. "
        f"Prop cues: {visual_profile['prop_keywords']}. "
        f"Mood cues: {visual_profile['mood_keywords']}. "
        "Use a Joseon court documentary painting style adapted for a web thumbnail: aged hanji paper, fine ink outlines, "
        "faded mineral pigments, calm flat perspective, and restrained palace-record mood. "
        "If the post centers on people, use one or two prominent half-length, seated, or medium-close figures with soft faces, "
        "correct Joseon clothing, refined posture, and historically plausible gestures; people do not need to be tiny. "
        "Use symbolic Joseon-era objects such as palace wooden floors, hanji documents, ink brushes, books, "
        "food trays, maps, seals, folding screens, carved wooden furniture, or architectural details when relevant. "
        "Do not include the post title, captions, signs, decorative calligraphy, modern objects, fantasy crowns, or inaccurate court costumes. "
        "If documents or letters are part of the scene, use only subtle brush marks as prop detail, not title-like typography. "
        f"Avoid fake Korean characters, glossy digital cartoon rendering, anime, manga, and {visual_profile['negative_visuals']}. "
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
        "Use Joseon court documentary painting aesthetics adapted into a polished editorial thumbnail: aged hanji paper texture, "
        "fine restrained ink outlines, faded natural mineral pigments, calm flat perspective, and palace-record composure. "
        "For human figures, faces may be visible and figures may be prominent in the frame. Use half-length, seated, or medium-close compositions "
        "when the post centers on people; keep expressions soft, calm, respectful, and Joseon portrait-like rather than photorealistic portrait claims. "
        "Render clothing folds, collars, hats, hair ornaments, and carved furniture with careful historical restraint, not modern fashion illustration. "
        f"Visual taxonomy role: {visual_profile['role_label']}. "
        f"Allowed clothing and props: {visual_profile['allowed_clothing']}. "
        f"Forbidden clothing and props: {visual_profile['forbidden_clothing']}. "
        f"Primary place type: {visual_profile['place_label']}. "
        f"Joseon space cues: {visual_profile['space_keywords']}. "
        f"Relevant prop cues: {visual_profile['prop_keywords']}. "
        f"Mood and composition cues: {visual_profile['mood_keywords']}. "
        f"Strictly avoid Japanese visual language and style: {visual_profile['negative_visuals']}. "
        "Also avoid anime, manga, ukiyo-e, Japanese screen-painting composition, glossy digital cartoon style, modern webtoon style, cinematic drama stills, and photorealism. "
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


def search_history_providers(keyword: str, providers: list[str] | None = None) -> list[dict[str, str]]:
    query_candidates = _history_query_candidates(keyword)
    provider_names = _resolve_history_providers(keyword, providers or ["auto"])
    resources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    search_jobs = [
        (query, provider_name, _history_search_provider(provider_name))
        for query in query_candidates
        for provider_name in provider_names
        if _history_search_provider(provider_name) is not None
    ]

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(search_jobs)))) as executor:
        futures = {
            executor.submit(search, query): query
            for query, _, search in search_jobs
            if search is not None
        }
        for future, query in futures.items():
            try:
                found_items = future.result()
            except Exception:
                found_items = []
            for item in found_items:
                url = str(item.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                resources.append(_prepare_history_resource(item, keyword, query))

    verified_resources = [item for item in resources if item.get("result_type") == "verified"]
    second_pass_queries = _secondary_query_candidates(keyword, verified_resources)
    if second_pass_queries:
        for query in second_pass_queries:
            for provider_name in provider_names:
                search = _history_search_provider(provider_name)
                if search is None:
                    continue
                for item in search(query):
                    url = str(item.get("url") or "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    resources.append(_prepare_history_resource(item, keyword, query))
    return _rank_history_resources(keyword, resources)[:12]


def _history_query_candidates(keyword: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", keyword).strip()
    if not cleaned:
        return []
    return [cleaned]


def _secondary_query_candidates(original_keyword: str, resources: list[dict[str, str]]) -> list[str]:
    original_compact = original_keyword.replace(" ", "")
    combined = " ".join(
        str(resource.get(key) or "")
        for resource in resources[:6]
        for key in ["title", "description", "content_excerpt"]
    )
    queries: list[str] = []
    anchors = _event_terms_for_filter(original_keyword) or _important_terms_for_score(original_keyword)
    clue_patterns = [r"([가-힣]{2,5})\([^)]+\)"]
    for pattern in clue_patterns:
        for match in re.findall(pattern, combined):
            clue = re.sub(r"\s+", " ", match).strip()
            clue = re.sub(r"(의|이|가|은|는|을|를)$", "", clue)
            compact_clue = clue.replace(" ", "")
            if len(compact_clue) < 2 or compact_clue in original_compact:
                continue
            if compact_clue in {"공주", "옹주", "대군", "왕후", "임금", "전하", "세자", "신하", "있던", "있는", "하던"}:
                continue
            if compact_clue.endswith(("하던", "있던")):
                continue
            for anchor in anchors[:2]:
                if anchor and anchor not in compact_clue:
                    queries.append(f"{clue} {anchor}")
    return list(dict.fromkeys(queries))[:3]


def _prepare_history_resource(item: dict[str, str], original_keyword: str, matched_query: str) -> dict[str, str]:
    prepared = _with_verification_status(item)
    return {
        **prepared,
        "matched_query": matched_query,
        "relevance_score": f"{_history_resource_score(original_keyword, prepared, matched_query):.3f}",
    }


def _rank_history_resources(keyword: str, resources: list[dict[str, str]]) -> list[dict[str, str]]:
    ranked = [
        resource
        for resource in resources
        if _passes_history_resource_filter(keyword, resource)
    ]
    return sorted(ranked, key=lambda item: float(item.get("relevance_score") or 0), reverse=True)


def _passes_history_resource_filter(keyword: str, resource: dict[str, str]) -> bool:
    terms = _event_terms_for_filter(keyword)
    if not terms:
        return True
    haystack = _resource_haystack(resource)
    if any(term in haystack for term in terms):
        return True
    return str(resource.get("result_type") or "") == "search_link" and any(term in str(resource.get("matched_query") or "") for term in terms)


def _history_resource_score(keyword: str, resource: dict[str, str], matched_query: str) -> float:
    score = float(resource.get("confidence") or 0)
    status = str(resource.get("verification_status") or "")
    if status == "primary_verified":
        score += 1.5
    elif status == "secondary_only":
        score += 0.35
    elif status == "unverified":
        score -= 0.2

    haystack = _resource_haystack(resource)
    compact_keyword = keyword.replace(" ", "")
    compact_haystack = haystack.replace(" ", "")
    if compact_keyword and compact_keyword in compact_haystack:
        score += 0.4
    for term in _important_terms_for_score(keyword):
        if term in haystack:
            score += 0.25
        else:
            score -= 0.25
    return score


def _important_terms_for_score(keyword: str) -> list[str]:
    compact = keyword.replace(" ", "")
    terms = [name for name in KING_NAMES if name in compact]
    terms.extend(_event_terms_for_filter(keyword))
    return list(dict.fromkeys(terms))


def _event_terms_for_filter(keyword: str) -> list[str]:
    compact = keyword.replace(" ", "")
    terms = []
    for term in ["어찰", "편지", "서찰", "기행", "사건", "일화"]:
        if term in compact:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _resource_haystack(resource: dict[str, str]) -> str:
    return " ".join(
        str(resource.get(key) or "")
        for key in ["title", "description", "content_excerpt"]
    )


def _with_verification_status(item: dict[str, str]) -> dict[str, str]:
    if item.get("verification_status"):
        return item
    result_type = str(item.get("result_type") or "")
    source_type = str(item.get("source_type") or "")
    can_quote = str(item.get("can_quote") or "").lower() == "true" or item.get("can_quote") is True
    return {**item, "verification_status": _verification_status(source_type, result_type, can_quote)}


def _resolve_history_providers(keyword: str, providers: list[str]) -> list[str]:
    normalized = " ".join(providers or ["auto"]).lower()
    if "auto" not in normalized:
        return [provider for provider in providers if _history_search_provider(provider) is not None]

    compact_keyword = keyword.replace(" ", "")
    if any(term in compact_keyword for term in ["어찰", "편지", "서찰", "고문서", "문집", "원문"]):
        return ["kostma", "nlk", "museum", "sillok", "encykorea", "web"]
    if any(term in compact_keyword for term in ["복식", "유물", "소장품", "그림", "초상", "어진", "이미지"]):
        return ["museum", "encykorea", "web", "sillok"]
    if any(term in compact_keyword for term in ["개괄", "뜻", "의미", "정리", "설명"]):
        return ["encykorea", "sillok", "web"]
    return ["sillok", "encykorea", "museum", "nlk", "kostma", "web"]


def _search_encykorea_seed(keyword: str) -> list[dict[str, str]]:
    if not ENCYKOREA_SEED_DIR.exists():
        return []
    normalized_keyword = keyword.replace(" ", "").lower()
    matches: list[tuple[int, dict[str, str]]] = []
    for path in ENCYKOREA_SEED_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = _parse_seed_frontmatter(text)
        haystack = f"{metadata.get('title', '')} {metadata.get('keywords', '')} {body[:3000]}"
        normalized_haystack = haystack.replace(" ", "").lower()
        if normalized_keyword not in normalized_haystack:
            continue
        title = metadata.get("title") or path.stem
        score = 2 if normalized_keyword in str(title).replace(" ", "").lower() else 1
        matches.append(
            (
                score,
                {
                    "title": title,
                    "provider": "한국민족문화대백과사전",
                    "url": metadata.get("source_url") or f"https://encykorea.aks.ac.kr/Article/{path.stem}",
                    "description": _resource_description("encyclopedia", "verified", _clean_html(body)[:180]),
                    "source_type": "encyclopedia",
                    "result_type": "verified",
                    "verification_status": "secondary_only",
                    "content_excerpt": _clean_html(body)[:500],
                    "confidence": "0.82",
                    "can_quote": "true",
                },
            )
        )
    return [item for _, item in sorted(matches, key=lambda pair: pair[0], reverse=True)[:5]]


def _parse_seed_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not match:
        return {}, text
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, match.group(2)


def _search_museum(keyword: str) -> list[dict[str, str]]:
    search_url = f"https://www.museum.go.kr/site/main/relic/search/list?keyword={quote_plus(keyword)}"
    return _search_html_provider(
        keyword=keyword,
        provider="국립중앙박물관",
        source_type="museum_object",
        search_url=search_url,
        base_url="https://www.museum.go.kr",
        include_url_patterns=["/site/main/relic/", "/relic/"],
        fallback_title="국립중앙박물관 소장품 검색",
        trust=0.78,
        can_quote=False,
    )


def _search_kostma(keyword: str) -> list[dict[str, str]]:
    search_url = f"https://kostma.aks.ac.kr/dir/search.aspx?query={quote_plus(keyword)}"
    return _search_html_provider(
        keyword=keyword,
        provider="한국학자료센터",
        source_type="primary_source",
        search_url=search_url,
        base_url="https://kostma.aks.ac.kr",
        include_url_patterns=["kostma.aks.ac.kr", "/dir/", "/uci/"],
        fallback_title="한국학자료센터 고문서 검색",
        trust=0.82,
        can_quote=True,
    )


def _search_nlk(keyword: str) -> list[dict[str, str]]:
    search_url = f"https://www.nl.go.kr/NL/search/search.do?kwd={quote_plus(keyword)}"
    return _search_html_provider(
        keyword=keyword,
        provider="국립중앙도서관",
        source_type="library_record",
        search_url=search_url,
        base_url="https://www.nl.go.kr",
        include_url_patterns=["/NL/", "/kolisnet/", "/seoji/"],
        fallback_title="국립중앙도서관 통합검색",
        trust=0.76,
        can_quote=False,
    )


def _search_web_whitelist(keyword: str) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for provider, source_type, url_template in WEB_WHITELIST_SEARCHES:
        search_url = url_template.format(keyword=quote_plus(keyword))
        resources.extend(
            _search_html_provider(
                keyword=keyword,
                provider=provider,
                source_type=source_type,
                search_url=search_url,
                base_url=search_url,
                include_url_patterns=[""],
                fallback_title=f"{provider} 검색",
                trust=0.62,
                can_quote=False,
                fallback=False,
                limit=2,
            )
        )
    if resources:
        return resources[:5]
    return [
        _search_link_resource(
            keyword,
            "화이트리스트 웹 검색",
            "웹 검색",
            "web_reference",
            WEB_WHITELIST_SEARCHES[0][2].format(keyword=quote_plus(keyword)),
        )
    ]


def _search_html_provider(
    *,
    keyword: str,
    provider: str,
    source_type: str,
    search_url: str,
    base_url: str,
    include_url_patterns: list[str],
    fallback_title: str,
    trust: float,
    can_quote: bool,
    fallback: bool = True,
    limit: int = 5,
) -> list[dict[str, str]]:
    body = _read_url(search_url)
    if not body:
        return [_search_link_resource(keyword, fallback_title, provider, source_type, search_url)] if fallback else []
    candidates = _extract_search_candidates(body, base_url, keyword, include_url_patterns)
    resources = [
        _build_deep_resource(
            keyword=keyword,
            provider=provider,
            source_type=source_type,
            title=title,
            url=url,
            trust=trust,
            can_quote=can_quote,
        )
        for title, url in candidates[:limit]
    ]
    return resources or ([_search_link_resource(keyword, fallback_title, provider, source_type, search_url)] if fallback else [])


def _extract_search_candidates(
    body: str,
    base_url: str,
    keyword: str,
    include_url_patterns: list[str],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    keyword_terms = [term for term in re.split(r"\s+", keyword.strip()) if len(term) >= 2]
    for href, raw_title in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", body, re.I | re.S):
        title = _clean_html(raw_title)
        if len(title) < 2:
            continue
        url = urljoin(base_url, html.unescape(href))
        if url in seen_urls or url.startswith(("javascript:", "#", "mailto:")):
            continue
        if include_url_patterns != [""] and not any(pattern in url for pattern in include_url_patterns):
            continue
        if keyword_terms and not any(term in title or term in _clean_html(body[:5000]) for term in keyword_terms):
            continue
        seen_urls.add(url)
        candidates.append((title[:120], url))
    return candidates


def _build_deep_resource(
    *,
    keyword: str,
    provider: str,
    source_type: str,
    title: str,
    url: str,
    trust: float,
    can_quote: bool,
) -> dict[str, str]:
    detail_body = _read_url(url, timeout=2)
    excerpt = _detail_excerpt(detail_body) if detail_body else ""
    confidence = _resource_confidence(keyword, title, excerpt, trust)
    result_type = "verified" if excerpt else "search_result"
    verification_status = _verification_status(source_type, result_type, can_quote and bool(excerpt))
    summary = excerpt[:180] if excerpt else "검색 결과 목록에서 확인한 항목입니다. 상세 본문은 링크에서 확인해야 합니다."
    return {
        "title": title,
        "provider": provider,
        "url": url,
        "description": _resource_description(source_type, result_type, summary),
        "source_type": source_type,
        "result_type": result_type,
        "verification_status": verification_status,
        "content_excerpt": excerpt[:500] if excerpt else "",
        "confidence": f"{confidence:.2f}",
        "can_quote": "true" if can_quote and bool(excerpt) else "false",
    }


def _search_link_resource(
    keyword: str,
    title: str,
    provider: str,
    source_type: str,
    url: str,
) -> dict[str, str]:
    return {
        "title": f"{keyword} {title}",
        "provider": provider,
        "url": url,
        "description": _resource_description(source_type, "search_link", "검색 결과 페이지 링크입니다. 자료 본문 확인 뒤 인용해야 합니다."),
        "source_type": source_type,
        "result_type": "search_link",
        "verification_status": "unverified",
        "content_excerpt": "",
        "confidence": "0.30",
        "can_quote": "false",
    }


def _resource_description(source_type: str, result_type: str, summary: str) -> str:
    result_label = "확인된 자료" if result_type == "verified" else "검색 결과" if result_type == "search_result" else "검색 링크"
    return f"[{source_type} · {result_label}] {summary}"


def _verification_status(source_type: str, result_type: str, can_quote: bool) -> str:
    if result_type == "verified" and source_type == "primary_source":
        return "primary_verified"
    if result_type in {"verified", "search_result"} and source_type != "primary_source":
        return "secondary_only"
    if result_type in {"search_result", "search_link"}:
        return "unverified"
    return "not_found"


def _resource_confidence(keyword: str, title: str, excerpt: str, trust: float) -> float:
    compact_keyword = keyword.replace(" ", "")
    compact_title = title.replace(" ", "")
    compact_excerpt = excerpt.replace(" ", "")
    match_score = 0.0
    if compact_keyword and compact_keyword in compact_title:
        match_score += 0.18
    if compact_keyword and compact_keyword in compact_excerpt:
        match_score += 0.16
    for term in [term for term in re.split(r"\s+", keyword) if len(term) >= 2]:
        if term in title:
            match_score += 0.04
        if term in excerpt:
            match_score += 0.03
    detail_bonus = 0.12 if excerpt else 0.0
    return min(0.95, trust + match_score + detail_bonus)


def _detail_excerpt(body: str | None) -> str:
    if not body:
        return ""
    body = re.sub(r"<script[\s\S]*?</script>", " ", body, flags=re.I)
    body = re.sub(r"<style[\s\S]*?</style>", " ", body, flags=re.I)
    text = _clean_html(body)
    text = re.sub(r"(본문 바로가기|메뉴 바로가기|로그인|회원가입|검색|공유|인쇄)", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:800]


def _read_url(url: str, timeout: int = 4) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(content_type, errors="replace")
    except (urllib.error.URLError, TimeoutError, UnicodeError, ValueError):
        return None


def _search_sillok(keyword: str) -> list[dict[str, str]]:
    url = SILLOK_SEARCH_URL.format(keyword=quote_plus(keyword))
    body = _read_url(url)
    if not body:
        return []

    resources = _parse_sillok_search_results(body)
    if resources:
        return resources[:5]
    return []


def _parse_sillok_search_results(body: str) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    result_boxes = re.findall(r'<div class="result-box">\s*(.*?)\s*</div>', body, re.S)
    for box in result_boxes:
        match = re.search(
            r'<a\b[^>]*href=["\']javascript:goView\(["\']([^"\']+)["\']\s*,\s*\d+\);?["\'][^>]*>(.*?)</a>',
            box,
            re.S,
        )
        if not match:
            match = re.search(
                r'<a\b[^>]*href=["\'][^"\']*/id/([a-z]{3}_\d{8}_\d{3})["\'][^>]*>(.*?)</a>',
                box,
                re.S | re.I,
            )
        if not match:
            continue
        article_id, title_html = match.groups()
        title = _clean_html(title_html)
        if not title:
            continue
        excerpt_match = re.search(r'<p class="text">(.*?)</p>', box, re.S)
        excerpt = _clean_html(excerpt_match.group(1)) if excerpt_match else ""
        resources.append(_sillok_resource(article_id, title, excerpt))
    if resources:
        return resources
    for article_id, title_html in re.findall(r"searchView\(['\"]([^'\"]+)['\"]\);?[^>]*>(.*?)</a>", body, re.S):
        title = _clean_html(title_html)
        if not title:
            continue
        resources.append(_sillok_resource(article_id, title, ""))
    return resources


def _sillok_resource(article_id: str, title: str, excerpt: str) -> dict[str, str]:
    excerpt = excerpt or _read_sillok_article_excerpt(article_id)
    summary = excerpt[:180] if excerpt else "조선왕조실록 검색 결과에서 조회한 기사입니다."
    return {
        "title": title,
        "provider": "국사편찬위원회 조선왕조실록",
        "url": f"https://sillok.history.go.kr/id/{article_id}",
        "description": _resource_description("primary_source", "verified", summary),
        "source_type": "primary_source",
        "result_type": "verified",
        "verification_status": "primary_verified",
        "content_excerpt": excerpt[:500],
        "confidence": "0.78",
        "can_quote": "true",
    }


def _read_sillok_article_excerpt(article_id: str) -> str:
    body = _read_url(f"https://sillok.history.go.kr/id/{article_id}", timeout=2)
    if not body:
        return ""
    return _detail_excerpt(body)[:500]


def _history_search_provider(provider_name: str):
    return {
        "sillok": _search_sillok,
        "encykorea": _search_encykorea_seed,
        "museum": _search_museum,
        "kostma": _search_kostma,
        "nlk": _search_nlk,
        "web": _search_web_whitelist,
    }.get(provider_name)


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
