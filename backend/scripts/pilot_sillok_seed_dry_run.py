from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.fetch_sillok_seed import BASE_URL, fetch_article_detail


PILOT_CASES = [
    {
        "sillok_id": "kca_11711024_002",
        "case": "yangnyeong_cat",
        "modern_search_phrases": ["양녕대군 고양이 사건", "양녕대군 고양이 일화"],
        "focus_terms": ["금빛 고양이", "신효창", "탁신", "세자"],
    },
    {
        "sillok_id": "kja_10904003_006",
        "case": "jangnoksu_yeonsangun_relation",
        "modern_search_phrases": ["장녹수 연산군 관계", "장녹수 일화", "연산군이 장녹수를 총애한 사례"],
        "focus_terms": ["장녹수", "녹수", "총애", "사랑", "말이라면 모두 따랐"],
    },
    {
        "sillok_id": "kja_10811025_002",
        "case": "jangnoksu_profile",
        "modern_search_phrases": ["장녹수 어떤 인물", "장녹수 출신", "연산군 장녹수"],
        "focus_terms": ["장녹수", "제안 대군", "가비", "총애", "숙원"],
    },
    {
        "sillok_id": "kea_10209001_003",
        "case": "gyeonghye_life",
        "modern_search_phrases": ["경혜공주 생애", "경혜공주 정종 혼인", "문종과 현덕왕후의 딸 경혜공주"],
        "focus_terms": ["경혜 공주", "경혜공주", "敬惠公主", "영양위", "정종", "鄭悰", "하가"],
    },
    {
        "sillok_id": "kna_12506028_004",
        "case": "imjin_militia_probe",
        "modern_search_phrases": ["임진왜란 의병", "의병 활동", "왜란 때 의병"],
        "focus_terms": ["의병", "義兵", "곽재우", "김천일", "김면"],
    },
]

ALIASES = {
    "양녕대군": {"strong": ["양녕대군", "이제", "李禔", "讓寧大君"], "weak": ["세자"]},
    "신효창": {"strong": ["신효창", "申孝昌"], "weak": []},
    "탁신": {"strong": ["탁신", "卓愼"], "weak": []},
    "장녹수": {"strong": ["장녹수", "張綠水", "錄壽"], "weak": ["녹수"]},
    "연산군": {"strong": ["연산군"], "weak": ["왕", "연산"]},
    "경혜공주": {"strong": ["경혜공주", "敬惠公主"], "weak": []},
    "정종": {"strong": ["鄭悰", "영양위"], "weak": ["정종"]},
    "문종": {"strong": ["문종", "文宗"], "weak": []},
    "현덕왕후": {"strong": ["현덕왕후", "顯德王后"], "weak": []},
    "임진왜란": {"strong": ["임진왜란", "壬辰倭亂"], "weak": ["왜란"]},
    "의병": {"strong": ["의병", "義兵"], "weak": []},
    "곽재우": {"strong": ["곽재우", "郭再祐"], "weak": ["재우"]},
    "김천일": {"strong": ["김천일", "金千鎰"], "weak": []},
}

TOPIC_TERMS = {
    "event": ["난", "반정", "전쟁", "왜란", "호란", "사건", "상소", "폐위", "창제", "반포", "처벌"],
    "person_relation": ["공주", "대군", "왕비", "후궁", "세자", "혼인", "하가", "총애", "졸", "묘지문", "형부", "가비"],
    "system_life": ["전세", "공납", "군역", "노비", "진휼", "시장", "농사", "흉년", "역병", "과거", "관직"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run five Sillok seed curation dry-run cycles without DB writes.")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--output", default="sillok_pilot_5_cycles_report.json")
    args = parser.parse_args()

    results = []
    for index, item in enumerate(PILOT_CASES, start=1):
        started = time.perf_counter()
        try:
            detail = fetch_article_detail(item["sillok_id"], "", include_original=False)
            people = find_people_and_aliases(detail, item["modern_search_phrases"])
            score, score_parts = score_article(detail, item["case"])
            results.append(
                {
                    "cycle": index,
                    "status": "ok",
                    "case": item["case"],
                    "sillok_id": item["sillok_id"],
                    "source_url": detail["url"],
                    "md_preview": {
                        "title": detail["title"],
                        "date": normalize_whitespace(detail["date"]),
                        "categories": detail["categories"],
                        "content": summarize(detail["translation"], 700),
                    },
                    "metadata_json": {
                        "sillok_id": item["sillok_id"],
                        **parse_date_metadata(item["sillok_id"], detail["date"]),
                        "source_url": detail["url"],
                        "categories": split_categories(detail["categories"]),
                        "people": people,
                        "modern_search_phrases": item["modern_search_phrases"],
                        "selection_case": item["case"],
                        "selection_score": score,
                        "selection_score_parts": score_parts,
                        "source_warning": source_warning(item["sillok_id"]),
                    },
                    "embedding_text": make_embedding_text(item, detail, people),
                    "elapsed_ms": elapsed_ms(started),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "cycle": index,
                    "status": "error",
                    "case": item["case"],
                    "sillok_id": item["sillok_id"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": elapsed_ms(started),
                }
            )
        print(
            f"cycle={index} status={results[-1]['status']} id={item['sillok_id']} elapsed_ms={results[-1]['elapsed_ms']}",
            flush=True,
        )
        if index < len(PILOT_CASES):
            time.sleep(args.delay)

    payload = {
        "policy": {
            "delay_seconds": args.delay,
            "detail_pages": len(PILOT_CASES),
            "db_write": False,
            "embedding_api": False,
            "include_original": False,
        },
        "results": results,
    }
    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={output_path.resolve()}")


def find_people_and_aliases(detail: dict[str, str], modern_search_phrases: list[str]) -> list[dict[str, object]]:
    source_haystack = " ".join(
        [
            detail["title"],
            detail["date"],
            detail["categories"],
            detail["translation"],
        ]
    )
    query_haystack = " ".join(modern_search_phrases)
    found = []
    for name, alias_groups in ALIASES.items():
        strong_aliases = alias_groups["strong"]
        weak_aliases = alias_groups["weak"]
        matched_in_source = [alias for alias in strong_aliases if alias in source_haystack]
        matched_in_query = [alias for alias in strong_aliases if alias in query_haystack]
        weak_matches = [alias for alias in weak_aliases if alias in source_haystack]
        if matched_in_source or (matched_in_query and weak_matches):
            found.append(
                {
                    "name": name,
                    "aliases": [alias for alias in [*strong_aliases, *weak_aliases] if alias != name],
                    "matched_terms": sorted(set([*matched_in_source, *matched_in_query, *weak_matches])),
                }
            )
    return found


def score_article(detail: dict[str, str], case: str) -> tuple[int, dict[str, int]]:
    haystack = " ".join([detail["title"], detail["categories"], detail["translation"][:1200], case])
    score_parts: dict[str, int] = {}
    score = 0
    for group, terms in TOPIC_TERMS.items():
        group_score = sum(1 for term in terms if term in haystack)
        score_parts[group] = group_score
        score += group_score
    length_bonus = 2 if 250 <= len(detail["translation"]) <= 2500 else 0
    title_bonus = 2 if len(detail["title"]) >= 8 else 0
    score_parts["length_bonus"] = length_bonus
    score_parts["title_bonus"] = title_bonus
    return score + length_bonus + title_bonus, score_parts


def make_embedding_text(item: dict[str, object], detail: dict[str, str], people: list[dict[str, object]]) -> str:
    people_text = ", ".join(
        f"{person['name']}({', '.join(str(alias) for alias in person['aliases'][:3])})" for person in people
    ) or "확인된 주요 인물 없음"
    modern = ", ".join(str(phrase) for phrase in item["modern_search_phrases"])
    focused_summary = focused_snippet(
        detail["translation"],
        people,
        item["modern_search_phrases"],
        [str(term) for term in item.get("focus_terms", [])],
    )
    lines = [
        f"이 기사는 {normalize_whitespace(detail['date']) or item['sillok_id']}의 조선왕조실록 기사이다.",
        f"주제는 {detail['title']}이다.",
        f"현대어 검색 표현으로는 {modern}와 관련된다.",
        f"관련 인물과 별칭은 {people_text}이다.",
    ]
    if detail["categories"]:
        lines.append(f"분류와 주제어는 {detail['categories']}이다.")
    lines.append(f"핵심 내용: {focused_summary}")
    return "\n".join(lines).strip()


def parse_date_metadata(article_id: str, date: str) -> dict[str, object]:
    normalized = normalize_whitespace(date)
    metadata: dict[str, object] = {"period": article_id[:3], "volume": None, "king_year": None, "month": None, "day": None, "article_no": None}
    match = re.search(
        r"(?P<period>.+?)(?P<volume>\d+)권,\s*.+?\s+(?P<year>\d+)년\s+(?P<month>\d+)월\s+(?P<day>\d+)일.*?(?P<article_no>\d+)/\d+\s+기사",
        normalized,
    )
    if match:
        metadata.update(
            {
                "period": match.group("period"),
                "volume": int(match.group("volume")),
                "king_year": int(match.group("year")),
                "month": int(match.group("month")),
                "day": int(match.group("day")),
                "article_no": int(match.group("article_no")),
            }
        )
    return metadata


def source_warning(article_id: str) -> str | None:
    if article_id.startswith(("kza", "kzb", "kzc")):
        return "고종·순종 계열 자료는 편찬 경위상 인용 주의"
    return None


def split_categories(categories: str) -> list[str]:
    return [item.strip() for item in categories.split("/") if item.strip()]


def summarize(text: str, limit: int) -> str:
    compact = normalize_whitespace(text)
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def focused_snippet(
    text: str,
    people: list[dict[str, object]],
    modern_search_phrases: list[str],
    focus_terms: list[str],
    limit: int = 650,
) -> str:
    compact = normalize_whitespace(text)
    if len(compact) <= limit:
        return compact
    focus_positions = [compact.find(term) for term in focus_terms if term and compact.find(term) >= 0]
    if focus_positions:
        return snippet_around(compact, min(focus_positions), limit)

    terms: list[str] = []
    for person in people:
        terms.append(str(person["name"]))
        terms.extend(str(term) for term in person.get("matched_terms", []))
    for phrase in modern_search_phrases:
        terms.extend(term for term in re.findall(r"[가-힣A-Za-z一-龥]{2,}", phrase) if len(term) >= 2)
    positions = [compact.find(term) for term in terms if term and compact.find(term) >= 0]
    if not positions:
        return summarize(compact, limit)
    return snippet_around(compact, min(positions), limit)


def snippet_around(text: str, center: int, limit: int) -> str:
    start = max(0, center - limit // 4)
    end = min(len(text), start + limit)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


if __name__ == "__main__":
    main()
