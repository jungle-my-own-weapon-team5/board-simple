from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_local
from app.models.ai import RagChunk, RagDocument


EVENT_TERMS = {
    "난",
    "반정",
    "전쟁",
    "왜란",
    "호란",
    "사건",
    "상소",
    "폐위",
    "창제",
    "반포",
    "처벌",
    "옥사",
    "사화",
    "환국",
    "조약",
    "강화",
    "토벌",
}
PERSON_RELATION_TERMS = {
    "공주",
    "대군",
    "왕비",
    "후궁",
    "세자",
    "세자빈",
    "혼인",
    "하가",
    "총애",
    "졸",
    "묘지문",
    "형부",
    "가비",
    "폐출",
    "유배",
    "복권",
    "공신",
    "책봉",
}
SYSTEM_LIFE_TERMS = {
    "전세",
    "공납",
    "군역",
    "노비",
    "진휼",
    "구휼",
    "시장",
    "농사",
    "흉년",
    "역병",
    "과거",
    "관직",
    "호구",
    "물가",
    "상속",
    "토지",
    "의학",
    "복식",
}
REPEATED_LOW_SIGNAL_TERMS = {
    "관직을 제수하다",
    "관직을 제수",
    "사정으로 삼다",
    "서용하다",
    "햇무리",
    "유성이",
    "지진이",
    "정사를 보다",
}
EVALUATION_BUNDLES = {
    "yangnyeong_cat": [["금빛 고양이", "고양이"], ["신효창"], ["탁신", "세자"]],
    "gyeonghye_life": [["경혜 공주", "경혜공주", "敬惠公主"], ["정종", "鄭悰", "영양위"], ["하가", "정미수", "부의"]],
    "jangnoksu": [["장녹수", "張綠水", "녹수"], ["연산군", "왕"], ["총애", "사랑", "말이라면"]],
    "hunminjeongeum_opposition": [["훈민정음", "언문"], ["최만리", "상소"], ["반대", "불가", "옳지"]],
    "munjong_first_wife": [["휘빈", "김씨"], ["세자빈"], ["폐출", "압승", "저주"]],
    "imjin_militia": [["의병", "義兵"], ["곽재우", "고경명", "김천일", "조헌", "김면"], ["왜적", "왜란", "토벌"]],
}

DEFAULT_BUCKET_RATIOS = {
    "event": 0.35,
    "person_relation": 0.25,
    "system_life": 0.25,
    "time_distribution": 0.15,
}


@dataclass
class SillokCandidate:
    sillok_id: str
    title: str
    period: str
    source_url: str
    categories: str = ""
    content: str = ""


@dataclass
class CandidateScore:
    sillok_id: str
    title: str
    period: str
    source_url: str
    score: float
    primary_bucket: str
    score_parts: dict[str, float]
    selection_reasons: list[str]
    evaluation_matches: list[str]
    sort_key: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Sillok article candidates for balanced RAG seed selection.")
    parser.add_argument("--output", default="../sillok_candidate_scores.json")
    parser.add_argument("--top-per-period", type=int, default=20)
    parser.add_argument("--base-quota", type=int, default=100)
    parser.add_argument("--max-quota", type=int, default=300)
    parser.add_argument("--quota-scale", type=int, default=100)
    parser.add_argument("--target-total", type=int, default=None, help="Trim selected items to this exact total after balanced selection.")
    parser.add_argument("--balanced", action="store_true", help="Select bucket-balanced candidates by period.")
    parser.add_argument("--min-score", type=float, default=0.0)
    args = parser.parse_args()

    db = get_session_local()()
    try:
        candidates = load_sillok_candidates_from_db(db)
    finally:
        db.close()

    scores = [score_candidate(candidate) for candidate in candidates]
    scores = [score for score in scores if score.score >= args.min_score]
    if args.balanced:
        grouped = select_balanced_by_period(scores, args.base_quota, args.max_quota, args.quota_scale)
    else:
        grouped = select_top_by_period(scores, args.top_per_period)
    if args.target_total is not None:
        grouped = trim_grouped_to_total(grouped, args.target_total)
    payload = {
        "policy": {
            "source": "current_db",
            "live_fetch": False,
            "top_per_period": args.top_per_period,
            "base_quota": args.base_quota,
            "max_quota": args.max_quota,
            "quota_scale": args.quota_scale,
            "target_total": args.target_total,
            "balanced": args.balanced,
            "bucket_ratios": DEFAULT_BUCKET_RATIOS,
            "evaluation_bundle_score_weight": 0,
            "min_score": args.min_score,
        },
        "total_candidates": len(candidates),
        "selected_count": sum(len(items) for items in grouped.values()),
        "periods": {
            period: [asdict(item) for item in items]
            for period, items in sorted(grouped.items())
        },
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"candidates={len(candidates)} selected={payload['selected_count']} report={output.resolve()}")


def load_sillok_candidates_from_db(db: Session) -> list[SillokCandidate]:
    documents = db.scalars(
        select(RagDocument)
        .where(RagDocument.source_url.like("https://sillok.history.go.kr/id/%"))
        .order_by(RagDocument.period, RagDocument.id)
    ).all()
    if not documents:
        return []
    chunks_by_document: dict[int, list[RagChunk]] = {}
    chunks = db.scalars(
        select(RagChunk)
        .where(RagChunk.document_id.in_([document.id for document in documents]))
        .order_by(RagChunk.document_id, RagChunk.chunk_index)
    ).all()
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

    candidates = []
    for document in documents:
        metadata = parse_metadata(document.metadata_json)
        content = "\n\n".join(chunk.content for chunk in chunks_by_document.get(document.id, []))
        candidates.append(
            SillokCandidate(
                sillok_id=str(metadata.get("sillok_id") or source_url_id(document.source_url)),
                title=document.title,
                period=clean_period(document.period),
                source_url=document.source_url,
                categories=str(metadata.get("categories") or ""),
                content=content,
            )
        )
    return candidates


def score_candidate(candidate: SillokCandidate) -> CandidateScore:
    haystack = normalize(" ".join([candidate.title, candidate.categories, candidate.content[:2400]]))
    title = normalize(candidate.title)
    content_len = len(normalize(candidate.content))

    event = term_score(haystack, EVENT_TERMS, 3.0)
    person_relation = term_score(haystack, PERSON_RELATION_TERMS, 2.7)
    system_life = term_score(haystack, SYSTEM_LIFE_TERMS, 2.4)
    evaluation_matches = evaluation_bundle_matches(haystack)
    title_clarity = min(8.0, max(0.0, len(title) / 8.0)) if title else 0.0
    length_score = length_quality_score(content_len)
    category_score = category_quality_score(candidate.categories)
    low_signal_penalty = term_score(haystack, REPEATED_LOW_SIGNAL_TERMS, 2.5)
    too_short_penalty = 8.0 if content_len < 80 else 0.0

    parts = {
        "event": event,
        "person_relation": person_relation,
        "system_life": system_life,
        "title_clarity": title_clarity,
        "length_quality": length_score,
        "category_quality": category_score,
        "low_signal_penalty": -low_signal_penalty,
        "too_short_penalty": -too_short_penalty,
    }
    score = sum(parts.values())
    bucket_scores = {
        "event": event,
        "person_relation": person_relation,
        "system_life": system_life,
    }
    primary_bucket = max(bucket_scores, key=bucket_scores.get)
    if bucket_scores[primary_bucket] <= 0:
        primary_bucket = "time_distribution"
    return CandidateScore(
        sillok_id=candidate.sillok_id,
        title=candidate.title,
        period=candidate.period,
        source_url=candidate.source_url,
        score=round(score, 3),
        primary_bucket=primary_bucket,
        score_parts={key: round(value, 3) for key, value in parts.items()},
        selection_reasons=selection_reasons(parts),
        evaluation_matches=evaluation_matches,
        sort_key=sort_key(candidate.sillok_id),
    )


def select_top_by_period(scores: list[CandidateScore], top_per_period: int) -> dict[str, list[CandidateScore]]:
    grouped: dict[str, list[CandidateScore]] = {}
    for score in scores:
        grouped.setdefault(score.period or "unknown", []).append(score)
    return {
        period: sorted(items, key=lambda item: (item.score, item.sort_key), reverse=True)[:top_per_period]
        for period, items in grouped.items()
    }


def select_balanced_by_period(
    scores: list[CandidateScore],
    base_quota: int,
    max_quota: int,
    quota_scale: int,
) -> dict[str, list[CandidateScore]]:
    grouped: dict[str, list[CandidateScore]] = {}
    for score in scores:
        grouped.setdefault(score.period or "unknown", []).append(score)

    selected: dict[str, list[CandidateScore]] = {}
    for period, items in grouped.items():
        quota = period_quota(len(items), base_quota, max_quota, quota_scale)
        bucket_targets = bucket_target_counts(quota)
        selected_items: list[CandidateScore] = []
        seen: set[str] = set()
        for bucket, target in bucket_targets.items():
            bucket_items = bucket_candidates(items, bucket)
            if bucket == "time_distribution":
                bucket_items = time_distributed_candidates(bucket_items or items, target)
            else:
                bucket_items = sorted(bucket_items, key=lambda item: (item.score, item.sort_key), reverse=True)
            added_for_bucket = 0
            for item in bucket_items:
                if item.sillok_id in seen:
                    continue
                selected_items.append(item)
                seen.add(item.sillok_id)
                added_for_bucket += 1
                if added_for_bucket >= target:
                    break
        if len(selected_items) < quota:
            for item in sorted(items, key=lambda item: (item.score, item.sort_key), reverse=True):
                if item.sillok_id in seen:
                    continue
                selected_items.append(item)
                seen.add(item.sillok_id)
                if len(selected_items) >= quota:
                    break
        selected[period] = selected_items[:quota]
    return selected


def trim_grouped_to_total(grouped: dict[str, list[CandidateScore]], target_total: int) -> dict[str, list[CandidateScore]]:
    if target_total < 0:
        raise ValueError("--target-total must be zero or greater")
    copied = {period: list(items) for period, items in grouped.items()}
    current_total = sum(len(items) for items in copied.values())
    if current_total <= target_total:
        return copied

    removable = []
    for period, items in copied.items():
        for index, item in enumerate(items):
            removable.append((item.score, item.sort_key, period, index))
    removable.sort()

    remove_by_period: dict[str, set[int]] = {}
    for _, _, period, index in removable[: current_total - target_total]:
        remove_by_period.setdefault(period, set()).add(index)

    return {
        period: [item for index, item in enumerate(items) if index not in remove_by_period.get(period, set())]
        for period, items in copied.items()
    }


def period_quota(candidate_count: int, base_quota: int, max_quota: int, quota_scale: int) -> int:
    if candidate_count <= 0:
        return 0
    quota = base_quota + candidate_count // max(1, quota_scale)
    return min(candidate_count, max_quota, max(1, quota))


def bucket_target_counts(quota: int) -> dict[str, int]:
    targets = {bucket: int(quota * ratio) for bucket, ratio in DEFAULT_BUCKET_RATIOS.items()}
    while sum(targets.values()) < quota:
        for bucket in ["event", "person_relation", "system_life", "time_distribution"]:
            targets[bucket] += 1
            if sum(targets.values()) >= quota:
                break
    return targets


def bucket_candidates(items: list[CandidateScore], bucket: str) -> list[CandidateScore]:
    if bucket == "time_distribution":
        return items
    return [item for item in items if item.primary_bucket == bucket]


def time_distributed_candidates(items: list[CandidateScore], target: int) -> list[CandidateScore]:
    if target <= 0:
        return []
    sorted_items = sorted(items, key=lambda item: item.sort_key)
    if len(sorted_items) <= target:
        return sorted_items
    selected = []
    for index in range(target):
        position = round(index * (len(sorted_items) - 1) / max(1, target - 1))
        selected.append(sorted_items[position])
    return selected


def selection_reasons(parts: dict[str, float]) -> list[str]:
    positive = [
        key
        for key in ["event", "person_relation", "system_life", "title_clarity", "length_quality", "category_quality"]
        if parts.get(key, 0) > 0
    ]
    penalties = [key for key in ["low_signal_penalty", "too_short_penalty"] if parts.get(key, 0) < 0]
    return [*positive[:5], *penalties]


def term_score(text: str, terms: set[str], weight: float) -> float:
    return sum(weight for term in terms if term and term in text)


def evaluation_bundle_matches(text: str) -> list[str]:
    matched_cases: list[str] = []
    for case_name, groups in EVALUATION_BUNDLES.items():
        if not groups or not any(term in text for term in groups[0]):
            continue
        matched_groups = 0
        for alternatives in groups:
            if any(term in text for term in alternatives):
                matched_groups += 1
        if matched_groups >= 2:
            matched_cases.append(case_name)
    return matched_cases


def length_quality_score(content_len: int) -> float:
    if content_len <= 0:
        return 0.0
    if 250 <= content_len <= 2500:
        return 6.0
    if 80 <= content_len < 250:
        return 2.0
    if 2500 < content_len <= 6000:
        return 3.0
    return 1.0


def category_quality_score(categories: str) -> float:
    if not categories:
        return 0.0
    groups = [item.strip() for item in categories.split("/") if item.strip()]
    return min(5.0, len(groups) * 1.5)


def parse_metadata(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def source_url_id(source_url: str) -> str:
    match = re.search(r"/id/([^/?#]+)", source_url)
    return match.group(1) if match else ""


def sort_key(sillok_id: str) -> str:
    return sillok_id or ""


def clean_period(period: str) -> str:
    return re.sub(r"\d+$", "", period or "").strip()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


if __name__ == "__main__":
    main()
