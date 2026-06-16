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

BASE_URL = "https://contents.history.go.kr"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "rag_seed" / "overview" / "sinpyeon_hanguksa"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Sinpyeon Hanguksa Joseon overview pages as RAG seed Markdown.")
    parser.add_argument("--start-volume", type=int, default=22)
    parser.add_argument("--end-volume", type=int, default=36)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    if args.clean and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for volume in range(args.start_volume, args.end_volume + 1):
        volume_id = f"nh_{volume:03d}"
        volume_dir = OUTPUT_DIR / volume_id
        volume_dir.mkdir(parents=True, exist_ok=True)
        try:
            toc = collect_leaf_toc(volume_id, volume_dir)
        except Exception as exc:
            if not args.continue_on_error:
                raise
            append_failed_volume(volume_dir, volume_id, exc)
            print(f"{volume_id}: failed_toc error={exc}", file=sys.stderr, flush=True)
            continue
        written = 0
        skipped = 0
        failed = 0
        for index, entry in enumerate(toc, start=1):
            output_path = volume_dir / f"{index:04d}-{entry['level_id']}.md"
            if output_path.exists():
                skipped += 1
                continue
            try:
                page = parse_content_page(entry["level_id"])
            except Exception as exc:
                if not args.continue_on_error:
                    raise
                failed += 1
                append_failed_page(volume_dir, entry, exc)
                print(f"failed level_id={entry['level_id']} error={exc}", file=sys.stderr, flush=True)
                continue
            if not page["content"]:
                continue
            output_path.write_text(to_markdown(entry, page), encoding="utf-8")
            written += 1
            total += 1
            time.sleep(args.delay)
        print(f"{volume_id}: written={written} skipped={skipped} failed={failed} leaf_pages={len(toc)}", flush=True)

    print(f"total_written={total}", flush=True)


def collect_leaf_toc(volume_id: str, volume_dir: Path) -> list[dict[str, str]]:
    cache_path = volume_dir / "leaf_toc.tsv"
    if cache_path.exists():
        return read_toc_cache(cache_path)

    html_text = fetch_text(f"{BASE_URL}/front/nh/view.do?levelId={volume_id}_0010")
    nodes = []
    for level_id, title_html in re.findall(
        r'<li[^>]+id="(nh_\d{3}(?:_\d{4})*)"[^>]*>\s*<span[^>]*>(.*?)</span>',
        html_text,
        re.S,
    ):
        if not level_id.startswith(volume_id):
            continue
        nodes.append({"level_id": level_id, "title": clean_text(title_html)})

    ids = [node["level_id"] for node in nodes]
    leaf_nodes = [
        node
        for node in nodes
        if not any(other != node["level_id"] and other.startswith(f"{node['level_id']}_") for other in ids)
    ]
    write_toc_cache(cache_path, leaf_nodes)
    return leaf_nodes


def read_toc_cache(path: Path) -> list[dict[str, str]]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        level_id, title = line.split("\t", 1)
        entries.append({"level_id": level_id, "title": title})
    return entries


def write_toc_cache(path: Path, entries: list[dict[str, str]]) -> None:
    lines = [f"{entry['level_id']}\t{entry['title']}" for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_failed_page(volume_dir: Path, entry: dict[str, str], exc: Exception) -> None:
    failed_path = volume_dir / "failed_pages.tsv"
    with failed_path.open("a", encoding="utf-8") as file:
        file.write(f"{entry['level_id']}\t{entry['title']}\t{type(exc).__name__}: {exc}\n")


def append_failed_volume(volume_dir: Path, volume_id: str, exc: Exception) -> None:
    failed_path = volume_dir / "failed_volume.tsv"
    with failed_path.open("a", encoding="utf-8") as file:
        file.write(f"{volume_id}\t{type(exc).__name__}: {exc}\n")


def parse_content_page(level_id: str) -> dict[str, str]:
    html_text = fetch_text(f"{BASE_URL}/front/nh/view.do?levelId={level_id}")
    path_titles = extract_breadcrumb_titles(html_text)
    content = extract_body_text(html_text)
    return {
        "source_url": f"{BASE_URL}/front/nh/view.do?levelId={level_id}",
        "path": " > ".join(path_titles),
        "content": content,
    }


def extract_breadcrumb_titles(html_text: str) -> list[str]:
    match = re.search(r'<section class="lnb">(.*?)</section>', html_text, re.S)
    if not match:
        return []
    titles = re.findall(r"<a[^>]*>(.*?)</a>", match.group(1), re.S)
    return [clean_text(title) for title in titles if clean_text(title) and clean_text(title) != "신편 한국사"]


def extract_body_text(html_text: str) -> str:
    start = html_text.find("<!-- content area -->")
    if start == -1:
        start = html_text.find('<div class="content">')
    if start == -1:
        return ""
    end_candidates = [
        index
        for index in [
            html_text.find('<div class="footnote_box"', start),
            html_text.find('<p class="message"', start),
            html_text.find("<!--// content area -->", start),
        ]
        if index != -1
    ]
    end = min(end_candidates) if end_candidates else len(html_text)
    content_html = html_text[start:end]
    paragraph_htmls = re.findall(r"<p(?:\s+[^>]*)?>(.*?)</p>", content_html, re.S)
    paragraphs = [clean_text(paragraph) for paragraph in paragraph_htmls]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def to_markdown(entry: dict[str, str], page: dict[str, str]) -> str:
    level_id = entry["level_id"]
    title = entry["title"]
    volume = level_id.split("_")[1]
    frontmatter = {
        "title": title,
        "period": "조선 시대",
        "source_type": "overview",
        "corpus": "sinpyeon_hanguksa",
        "source_url": page["source_url"],
        "level_id": level_id,
        "volume": volume,
        "section_path": page["path"],
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f'{key}: "{escape_frontmatter(value)}"')
    lines.extend(["---", "", f"# {title}", ""])
    if page["path"]:
        lines.extend([f"- 경로: {page['path']}", ""])
    lines.append(page["content"])
    return "\n".join(lines).strip() + "\n"


def fetch_text(url: str) -> str:
    for attempt in range(1, 6):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; WebBoardRagSeed/1.0; +local-dev)"},
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
            if attempt == 5:
                raise
            wait_seconds = min(2**attempt, 30)
            print(f"retry attempt={attempt} wait={wait_seconds}s url={url} error={exc}", file=sys.stderr, flush=True)
            time.sleep(wait_seconds)
    raise RuntimeError(f"Failed to fetch {url}")


def clean_text(value: str) -> str:
    value = re.sub(r"<span[^>]*content=\"(.*?)\"[^>]*>.*?</span>", r" \1 ", value, flags=re.S)
    value = re.sub(r"<br\s*/?>", "\n", value)
    value = re.sub(r"<.*?>", " ", value, flags=re.S)
    value = html.unescape(value)
    value = value.replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def slugify(value: str) -> str:
    quoted = quote(value, safe="")
    return quoted.replace("%", "").lower()[:80]


def escape_frontmatter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    main()
