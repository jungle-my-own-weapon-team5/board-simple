from __future__ import annotations

import argparse
import html
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

BASE_URL = "https://sillok.history.go.kr"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "rag_seed" / "sillok"

RECORDS = [
    ("kaa", "태조실록"),
    ("kba", "정종실록"),
    ("kca", "태종실록"),
    ("kda", "세종실록"),
    ("kea", "문종실록"),
    ("kfa", "단종실록"),
    ("kga", "세조실록"),
    ("kha", "예종실록"),
    ("kia", "성종실록"),
    ("kja", "연산군일기"),
    ("kka", "중종실록"),
    ("kla", "인종실록"),
    ("kma", "명종실록"),
    ("kna", "선조실록"),
    ("knb", "선조수정실록"),
    ("koa", "광해군중초본"),
    ("kob", "광해군정초본"),
    ("kpa", "인조실록"),
    ("kqa", "효종실록"),
    ("kra", "현종실록"),
    ("krb", "현종개수실록"),
    ("ksa", "숙종실록"),
    ("ksb", "숙종보궐정오"),
    ("kta", "경종실록"),
    ("ktb", "경종수정실록"),
    ("kua", "영조실록"),
    ("kva", "정조실록"),
    ("kwa", "순조실록"),
    ("kxa", "헌종실록"),
    ("kya", "철종실록"),
    ("kza", "고종실록"),
    ("kzb", "순종실록"),
    ("kzc", "순종실록부록"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Joseon Sillok articles into RAG seed Markdown files.")
    parser.add_argument("--limit-per-record", type=int, default=50, help="0 means all articles per selected record.")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--records", nargs="*", help="Optional record codes, e.g. kda kga.")
    parser.add_argument("--start-record", help="Select records from this code, e.g. kba.")
    parser.add_argument("--through-record", help="Select records from the beginning through this code, e.g. kva.")
    parser.add_argument("--include-original", action="store_true", help="Also save the classical Chinese original text.")
    args = parser.parse_args()

    selected = RECORDS
    if args.records:
        wanted = set(args.records)
        selected = [record for record in RECORDS if record[0] in wanted]
    elif args.start_record or args.through_record:
        selected = select_records_through(args.through_record)
        if args.start_record:
            selected = select_records_from(args.start_record, selected)

    if args.clean and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for code, record_name in selected:
        record_dir = OUTPUT_DIR / f"{code}-{slugify(record_name)}"
        record_dir.mkdir(parents=True, exist_ok=True)
        article_refs = collect_article_refs(code, args.limit_per_record, args.delay, record_dir)

        written = 0
        skipped = 0
        for index, (article_id, list_title) in enumerate(article_refs, start=1):
            output_path = record_dir / f"{index:04d}-{article_id}.md"
            if output_path.exists():
                skipped += 1
                continue

            detail = fetch_article_detail(article_id, list_title, include_original=args.include_original)
            if not detail["translation"] and not detail["original"]:
                continue
            output_path.write_text(to_markdown(record_name, article_id, detail), encoding="utf-8")
            written += 1
            total += 1
            time.sleep(args.delay)

        print(f"{code} {record_name}: written={written} skipped={skipped} refs={len(article_refs)}", flush=True)

    print(f"total files: {total}")


def collect_article_refs(code: str, limit: int, delay: float, record_dir: Path) -> list[tuple[str, str]]:
    cache_path = record_dir / "article_refs.tsv"
    if cache_path.exists():
        cached = read_article_ref_cache(cache_path)
        if limit <= 0 or len(cached) >= limit:
            return cached if limit <= 0 else cached[:limit]

    month_html = fetch_text(f"{BASE_URL}/search/inspectionMonthList.do?id={code}")
    month_ids = unique_in_order(re.findall(rf"{code}_\d{{6}}", month_html))

    article_refs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for month_id in month_ids:
        day_html = fetch_text(f"{BASE_URL}/search/inspectionDayList.do?id={month_id}")
        for article_id, title_html in re.findall(
            rf"searchView\('({code}_\d{{8}}_\d{{3}})'\);\">(.*?)</a>",
            day_html,
            re.S,
        ):
            if article_id in seen:
                continue
            seen.add(article_id)
            article_refs.append((article_id, clean_html(title_html)))
            if limit > 0 and len(article_refs) >= limit:
                return article_refs
        time.sleep(delay)
    write_article_ref_cache(cache_path, article_refs)
    return article_refs


def fetch_article_detail(article_id: str, fallback_title: str, include_original: bool) -> dict[str, str]:
    page_html = fetch_text(f"{BASE_URL}/id/{article_id}")
    date = extract_date(page_html)
    title = extract_title(page_html) or fallback_title
    translation = extract_view_text(page_html, "국역")
    original = extract_view_text(page_html, "원문") if include_original else ""
    categories = extract_categories(page_html)
    return {
        "title": title,
        "date": date,
        "translation": translation,
        "original": original,
        "categories": categories,
        "url": f"{BASE_URL}/id/{article_id}",
    }


def fetch_text(url: str) -> str:
    for attempt in range(1, 11):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; WebBoardRagSeed/1.0; +local-dev)",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except (
            ConnectionError,
            ConnectionResetError,
            TimeoutError,
            socket.timeout,
            urllib.error.URLError,
            urllib.error.HTTPError,
        ) as exc:
            if attempt == 10:
                raise
            wait_seconds = min(2**attempt, 120)
            print(f"retry attempt={attempt} wait={wait_seconds}s url={url} error={exc}", file=sys.stderr, flush=True)
            time.sleep(wait_seconds)
    raise RuntimeError(f"Failed to fetch {url}")


def read_article_ref_cache(path: Path) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        article_id, title = line.split("\t", 1)
        refs.append((article_id, title))
    return refs


def write_article_ref_cache(path: Path, refs: list[tuple[str, str]]) -> None:
    lines = [f"{article_id}\t{title}" for article_id, title in refs]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_date(page_html: str) -> str:
    match = re.search(r'<p class="date">\s*(.*?)\s*</p>', page_html, re.S)
    return clean_html(match.group(1)) if match else ""


def extract_title(page_html: str) -> str:
    match = re.search(r'<p class="date">.*?</p>\s*<h3>(.*?)</h3>', page_html, re.S)
    return clean_html(match.group(1)) if match else ""


def extract_view_text(page_html: str, title: str) -> str:
    pattern = (
        rf'<h4 class="view-title">{re.escape(title)}</h4>\s*'
        r'<div class="view-text">\s*(.*?)\s*</div>'
    )
    match = re.search(pattern, page_html, re.S)
    if not match:
        return ""

    paragraph_htmls = re.findall(r"<p class='paragraph'>(.*?)</p>", match.group(1), re.S)
    paragraphs = [clean_html(paragraph) for paragraph in paragraph_htmls]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def extract_categories(page_html: str) -> str:
    match = re.search(r"【분류】(.*?)</li>", page_html, re.S)
    return clean_html(match.group(1)) if match else ""


def to_markdown(record_name: str, article_id: str, detail: dict[str, str]) -> str:
    title = f"{record_name}: {detail['title']}"
    frontmatter = {
        "title": title,
        "period": record_name,
        "source_url": detail["url"],
        "sillok_id": article_id,
        "date": detail["date"],
        "categories": detail["categories"],
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f'{key}: "{escape_frontmatter(value)}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {detail['title']}")
    lines.append("")
    if detail["date"]:
        lines.append(f"- 출전: {detail['date']}")
    lines.append(f"- 기사 ID: {article_id}")
    lines.append(f"- URL: {detail['url']}")
    if detail["categories"]:
        lines.append(f"- 분류: {detail['categories']}")
    lines.append("")
    if detail["translation"]:
        lines.append("## 국역")
        lines.append("")
        lines.append(detail["translation"])
        lines.append("")
    if detail["original"]:
        lines.append("## 원문")
        lines.append("")
        lines.append(detail["original"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def select_records_through(code: str) -> list[tuple[str, str]]:
    if not code:
        return RECORDS
    for index, (record_code, _) in enumerate(RECORDS):
        if record_code == code:
            return RECORDS[: index + 1]
    raise SystemExit(f"Unknown record code for --through-record: {code}")


def select_records_from(code: str, records: list[tuple[str, str]]) -> list[tuple[str, str]]:
    for index, (record_code, _) in enumerate(records):
        if record_code == code:
            return records[index:]
    raise SystemExit(f"Unknown record code for --start-record: {code}")


def clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value)
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def slugify(value: str) -> str:
    quoted = quote(value, safe="")
    return quoted.replace("%", "").lower()[:80]


def escape_frontmatter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    main()
