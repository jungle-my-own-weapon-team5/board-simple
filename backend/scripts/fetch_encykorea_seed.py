from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BASE_URL = "https://encykorea.aks.ac.kr"
BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BACKEND_DIR / "raw_seed" / "encykorea"
OUTPUT_DIR = BACKEND_DIR / "rag_seed" / "overview" / "encykorea"
ROYAL_TITLES = {
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
}
PREFERRED_EIDS = {
    "태조": "E0059033",
    "정종": "E0050884",
    "태종": "E0059039",
    "세종": "E0029857",
    "문종": "E0019665",
    "과거": "E0004562",
}

DEFAULT_QUERIES: list[tuple[str, str]] = [
    ("태조", "태조"),
    ("정종", "정종"),
    ("태종", "태종"),
    ("세종", "세종"),
    ("문종", "문종"),
    ("단종", "단종"),
    ("세조", "세조"),
    ("예종", "예종"),
    ("성종", "성종"),
    ("연산군", "연산군"),
    ("중종", "중종"),
    ("인종", "인종"),
    ("명종", "명종"),
    ("선조", "선조"),
    ("광해군", "광해군"),
    ("인조", "인조"),
    ("효종", "효종"),
    ("현종", "현종"),
    ("숙종", "숙종"),
    ("경종", "경종"),
    ("영조", "영조"),
    ("정조", "정조"),
    ("순조", "순조"),
    ("헌종", "헌종"),
    ("철종", "철종"),
    ("고종", "고종"),
    ("훈민정음", "훈민정음"),
    ("집현전", "집현전"),
    ("경국대전", "경국대전"),
    ("과거", "과거"),
    ("사림", "사림"),
    ("훈구", "훈구"),
    ("사화", "사화"),
    ("계유정난", "계유정난"),
    ("임진왜란", "임진왜란"),
    ("정유재란", "정유재란"),
    ("병자호란", "병자호란"),
    ("붕당 정치", "붕당정치"),
    ("예송", "예송"),
    ("환국", "환국"),
    ("탕평책", "탕평책"),
    ("대동법", "대동법"),
    ("균역법", "균역법"),
    ("실학", "실학"),
    ("세도정치", "세도정치"),
    ("비변사", "비변사"),
    ("의정부", "의정부"),
    ("육조", "육조"),
    ("서원", "서원"),
    ("향약", "향약"),
    ("양반", "양반"),
    ("노비", "노비"),
    ("장영실", "장영실"),
    ("이순신", "이순신"),
    ("정약용", "정약용"),
    ("김홍도", "김홍도"),
    ("신윤복", "신윤복"),
]


class ThrottledFetcher:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.last_request_at = 0.0

    def fetch_text(self, url: str) -> str:
        for attempt in range(1, 6):
            self._wait_for_slot()
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; WebBoardRagSeed/1.0; +local-dev)",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
                    },
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.last_request_at = time.perf_counter()
                    return response.read().decode("utf-8", errors="replace")
            except (
                ConnectionError,
                ConnectionResetError,
                TimeoutError,
                socket.timeout,
                urllib.error.URLError,
                urllib.error.HTTPError,
            ) as exc:
                self.last_request_at = time.perf_counter()
                if attempt == 5:
                    raise
                wait_seconds = max(self.delay, min(2**attempt, 60))
                print(f"retry attempt={attempt} wait={wait_seconds:.1f}s url={url} error={exc}", file=sys.stderr, flush=True)
                time.sleep(wait_seconds)
        raise RuntimeError(f"Failed to fetch {url}")

    def _wait_for_slot(self) -> None:
        if not self.last_request_at:
            return
        elapsed = time.perf_counter() - self.last_request_at
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch EncyKorea overview articles as raw HTML and normalized RAG Markdown."
    )
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to wait between requests.")
    parser.add_argument("--limit-queries", type=int, default=0, help="Maximum curated queries to process. 0 means all.")
    parser.add_argument("--start-index", type=int, default=0, help="0-based index in the curated query list.")
    parser.add_argument("--max-articles", type=int, default=0, help="Stop after writing this many articles. 0 means no cap.")
    parser.add_argument("--max-candidates-per-query", type=int, default=8)
    parser.add_argument("--query", action="append", default=[], help="Extra query to process after the curated list.")
    parser.add_argument("--clean", action="store_true", help="Delete existing EncyKorea raw/normalized files first.")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    if args.clean:
        if RAW_DIR.exists():
            shutil.rmtree(RAW_DIR)
        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
    (RAW_DIR / "html").mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "articles").mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    queries = build_queries(args.query)
    if args.start_index:
        queries = queries[args.start_index :]
    if args.limit_queries:
        queries = queries[: args.limit_queries]

    fetcher = ThrottledFetcher(args.delay)
    written = 0
    skipped = 0
    failed = 0
    seen_eids = collect_existing_eids()

    for index, query_spec in enumerate(queries, start=args.start_index + 1):
        if args.max_articles and written >= args.max_articles:
            break
        query = query_spec["query"]
        preferred_title = query_spec["preferred_title"]
        try:
            preferred_eid = query_spec["eid"]
            selected = None
            if preferred_eid:
                candidates = [{"eid": preferred_eid, "title": preferred_title, "categories": ""}]
            else:
                candidates = search_candidates(fetcher, query)

            for candidate in candidates[: args.max_candidates_per_query]:
                eid = candidate["eid"]
                if eid in seen_eids:
                    skipped += 1
                    selected = {"status": "skipped", "eid": eid, "title": candidate.get("title", "")}
                    break
                article = fetch_article(fetcher, eid, query, preferred_title)
                if is_relevant_article(article, query, preferred_title):
                    write_article(article)
                    seen_eids.add(eid)
                    written += 1
                    selected = {"status": "written", "eid": eid, "title": article["title"]}
                    break
            if selected is None:
                failed += 1
                append_manifest(query, "", "", "no_relevant_candidate")
                print(f"[{index}/{len(queries)}] query={query} status=no_relevant_candidate", flush=True)
            else:
                append_manifest(query, selected["eid"], selected["title"], selected["status"])
                print(
                    f"[{index}/{len(queries)}] query={query} eid={selected['eid']} "
                    f"title={selected['title']} status={selected['status']}",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            append_manifest(query, "", "", f"{type(exc).__name__}: {exc}")
            print(f"[{index}/{len(queries)}] query={query} failed error={exc}", file=sys.stderr, flush=True)
            if not args.continue_on_error:
                raise

    print(f"done written={written} skipped={skipped} failed={failed}", flush=True)


def build_queries(extra_queries: list[str]) -> list[dict[str, str]]:
    queries = [
        {
            "query": query,
            "preferred_title": preferred_title,
            "eid": PREFERRED_EIDS.get(preferred_title, ""),
        }
        for query, preferred_title in DEFAULT_QUERIES
    ]
    queries.extend({"query": query, "preferred_title": query, "eid": ""} for query in extra_queries)
    return queries


def collect_existing_eids() -> set[str]:
    eids: set[str] = set()
    for path in OUTPUT_DIR.glob("E*.md"):
        eids.add(path.stem.split("-", 1)[0])
    for path in (RAW_DIR / "articles").glob("E*.json"):
        eids.add(path.stem.split("-", 1)[0])
    return eids


def search_candidates(fetcher: ThrottledFetcher, query: str) -> list[dict[str, str]]:
    encoded = urllib.parse.urlencode({"query": query})
    html_text = fetcher.fetch_text(f"{BASE_URL}/Article/Search?{encoded}")
    result_start = html_text.find('<div class="bo_gall')
    result_html = html_text[result_start:] if result_start != -1 else html_text
    candidates = []
    seen: set[str] = set()
    for match in re.finditer(r'<li>\s*<a href="/Article/(?P<eid>E\d+)" class="item">(?P<body>.*?)</a>\s*</li>', result_html, re.S):
        eid = match.group("eid")
        if eid in seen:
            continue
        seen.add(eid)
        body = match.group("body")
        candidates.append(
            {
                "eid": eid,
                "title": extract_search_title(body),
                "categories": ", ".join(extract_categories(body)),
            }
        )
    return candidates


def fetch_article(
    fetcher: ThrottledFetcher,
    eid: str,
    query: str,
    preferred_title: str,
) -> dict:
    source_url = f"{BASE_URL}/Article/{eid}"
    html_text = fetcher.fetch_text(source_url)
    article = parse_article_html(eid, html_text, source_url, query, preferred_title)
    article["_raw_html"] = html_text
    return article


def parse_article_html(
    eid: str,
    html_text: str,
    source_url: str,
    query: str,
    preferred_title: str,
) -> dict:
    title = extract_title(html_text) or preferred_title or query
    categories, head_description = extract_article_categories(html_text)
    summary_section = extract_section_html(html_text, "summary")
    summary = extract_summary_text(summary_section)
    keywords = extract_keywords(summary_section)
    definition = extract_detail_text(extract_section_html(html_text, "defi"))
    body_sections = extract_body_sections(html_text)
    period = next((category for category in categories if "조선" in category), "")
    if not period:
        period = next((category for category in categories if category.endswith("기")), "")

    return {
        "eid": eid,
        "title": title,
        "query": query,
        "preferred_title": preferred_title,
        "source": "한국민족문화대백과사전",
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "period": period,
        "head_description": head_description,
        "summary": summary,
        "keywords": keywords,
        "definition": definition,
        "sections": body_sections,
    }


def extract_search_title(card_html: str) -> str:
    match = re.search(r'<p class="subject">(.*?)</p>', card_html, re.S)
    if not match:
        return ""
    text = html_to_text(match.group(1))
    return re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()


def extract_title(html_text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html_text, re.S)
    if not match:
        return ""
    title = html_to_text(match.group(1))
    return re.sub(r"\s+-\s+한국민족문화대백과사전$", "", title).strip()


def extract_article_categories(html_text: str) -> tuple[list[str], str]:
    match = re.search(r'<div class="category">\s*<ul>(?P<ul>.*?)</ul>(?P<rest>.*?)</div>', html_text, re.S)
    if not match:
        return [], ""
    categories = extract_categories(match.group("ul"))
    head_match = re.search(r'<div class="head_cont">(.*?)</div>', match.group("rest"), re.S)
    head_description = html_to_text(head_match.group(1)) if head_match else ""
    return categories, head_description


def extract_categories(html_text: str) -> list[str]:
    return [html_to_text(value) for value in re.findall(r'class="cate\d+">(.*?)</(?:li|span)>', html_text, re.S)]


def extract_section_html(html_text: str, section_id: str) -> str:
    match = re.search(rf'<section id="{re.escape(section_id)}"[^>]*>(.*?)</section>', html_text, re.S)
    return match.group(1) if match else ""


def extract_summary_text(section_html: str) -> str:
    if not section_html:
        return ""
    detail_start = section_html.find('<div class="detail"')
    if detail_start == -1:
        return ""
    open_end = section_html.find(">", detail_start)
    detail_html = section_html[open_end + 1 :]
    detail_html = re.split(r'<div class="detail_keyword"', detail_html, maxsplit=1)[0]
    return html_to_text(detail_html)


def extract_keywords(section_html: str) -> list[str]:
    if not section_html:
        return []
    keywords = [html_to_text(value) for value in re.findall(r'/Article/Hashtag\?tag=[^"]*"[^>]*>(.*?)</a>', section_html, re.S)]
    return [keyword for keyword in keywords if keyword]


def extract_detail_text(section_html: str) -> str:
    if not section_html:
        return ""
    detail_start = section_html.find('<div class="detail"')
    if detail_start == -1:
        return ""
    open_end = section_html.find(">", detail_start)
    detail_html = section_html[open_end + 1 :]
    return html_to_text(detail_html)


def extract_body_sections(html_text: str) -> list[dict[str, str]]:
    body_start = html_text.find('<div id="body_content">')
    if body_start == -1:
        return []
    reference_start = html_text.find('<section id="reference"', body_start)
    body_html = html_text[body_start:reference_start] if reference_start != -1 else html_text[body_start:]
    sections = []
    for match in re.finditer(r'<section[^>]*class="content_section"[^>]*>(.*?)</section>', body_html, re.S):
        section_html = match.group(1)
        title_match = re.search(r'<h3 class="tit">(.*?)</h3>', section_html, re.S)
        title = html_to_text(title_match.group(1)) if title_match else ""
        text = extract_detail_text(section_html)
        if title and text:
            sections.append({"heading": title, "text": text})
    return sections


def is_relevant_article(article: dict, query: str, preferred_title: str) -> bool:
    title = normalize_key(article["title"])
    preferred = normalize_key(preferred_title)
    categories = " ".join(article.get("categories", []))

    if preferred_title in ROYAL_TITLES:
        royal_text = article.get("summary", "") + " " + article.get("definition", "") + " " + article.get("head_description", "")
        return (
            title == preferred
            and "인물" in categories
            and ("조선" in categories or "조선" in royal_text)
            and "왕" in royal_text
            and "재위" in royal_text
        )
    if preferred and title == preferred:
        return True
    return False


def write_article(article: dict) -> None:
    html_path = RAW_DIR / "html" / f"{article['eid']}.html"
    html_path.write_text(article.get("_raw_html", ""), encoding="utf-8")
    article_for_json = {key: value for key, value in article.items() if key != "_raw_html"}
    json_path = RAW_DIR / "articles" / f"{article['eid']}.json"
    json_path.write_text(json.dumps(article_for_json, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = OUTPUT_DIR / f"{article['eid']}.md"
    md_path.write_text(to_markdown(article), encoding="utf-8")


def to_markdown(article: dict) -> str:
    frontmatter = {
        "title": article["title"],
        "period": article.get("period", ""),
        "source_type": "overview",
        "corpus": "encykorea",
        "source": article.get("source", "한국민족문화대백과사전"),
        "source_url": article["source_url"],
        "article_id": article["eid"],
        "query": article["query"],
        "categories": ", ".join(article.get("categories", [])),
        "keywords": ", ".join(article.get("keywords", [])),
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f'{key}: "{escape_frontmatter(str(value))}"')
    lines.extend(["---", "", f"# {article['title']}", ""])

    summary = article.get("summary") or article.get("head_description")
    if summary:
        lines.extend(["## 검색용 요약", "", summary, ""])

    if article.get("keywords"):
        lines.extend(["## 핵심 키워드", ""])
        lines.append(", ".join(article["keywords"]))
        lines.append("")

    category_line = ", ".join(article.get("categories", []))
    if category_line or article.get("head_description"):
        lines.extend(["## 분류와 정의", ""])
        if category_line:
            lines.append(f"- 분류: {category_line}")
        if article.get("head_description"):
            lines.append(f"- 설명: {article['head_description']}")
        if article.get("definition"):
            lines.append(f"- 정의: {article['definition']}")
        lines.append("")

    if article.get("sections"):
        lines.extend(["## 개괄 본문", ""])
        for section in article["sections"]:
            lines.extend([f"### {section['heading']}", "", section["text"], ""])

    lines.extend(
        [
            "## 출처",
            "",
            f"{article['title']}, 한국민족문화대백과사전, {article['source_url']}",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def html_to_text(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<button.*?</button>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda match: f"\n\n### {html_to_text(match.group(1))}\n\n", value, flags=re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</p>\s*<p[^>]*>", "\n\n", value, flags=re.S | re.I)
    value = re.sub(r"</li>\s*<li[^>]*>", "\n- ", value, flags=re.S | re.I)
    value = re.sub(r"<li[^>]*>", "- ", value, flags=re.S | re.I)
    value = re.sub(r"<.*?>", " ", value, flags=re.S)
    value = unescape(value)
    value = value.replace("\u3000", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def normalize_key(value: str) -> str:
    value = html_to_text(value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\s+", "", value)
    return value.lower()


def append_manifest(query: str, eid: str, title: str, status: str) -> None:
    path = RAW_DIR / "manifest.tsv"
    is_new = not path.exists()
    with path.open("a", encoding="utf-8") as file:
        if is_new:
            file.write("fetched_at\tquery\teid\ttitle\tstatus\n")
        file.write(f"{datetime.now(timezone.utc).isoformat()}\t{query}\t{eid}\t{title}\t{status}\n")


def escape_frontmatter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    main()
