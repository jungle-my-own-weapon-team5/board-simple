from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TopicStatus = Literal["allow", "deny", "unknown"]


@dataclass(frozen=True)
class TopicDecision:
    status: TopicStatus
    reason: str


HISTORY_TOPIC_TERMS = [
    "역사",
    "조선",
    "고려",
    "신라",
    "백제",
    "고구려",
    "발해",
    "대한제국",
    "일제강점기",
    "왕",
    "왕실",
    "임금",
    "왕권",
    "세자",
    "대군",
    "공주",
    "옹주",
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
    "양녕",
    "효령",
    "충녕",
    "사도세자",
    "흥선대원군",
    "정몽주",
    "정도전",
    "황희",
    "신숙주",
    "한명회",
    "조광조",
    "정여립",
    "이순신",
    "류성룡",
    "허준",
    "신사임당",
    "황진이",
    "논개",
    "장녹수",
    "김만덕",
    "계유정난",
    "임진왜란",
    "병자호란",
    "훈민정음",
    "집현전",
    "붕당",
    "사림",
    "실록",
    "사료",
    "원문",
    "국역",
    "왕조",
    "궁궐",
    "관료",
    "문신",
    "무신",
    "유교",
    "불교",
    "성리학",
    "과거제",
    "대동법",
    "경국대전",
    "생활사",
    "문화사",
    "민속",
    "복식",
    "형벌",
    "전쟁",
    "열녀",
    "노비",
]

OBVIOUS_OFF_TOPIC_TERMS = [
    "파이썬",
    "코딩",
    "비동기",
    "자바스크립트",
    "리액트",
    "점심",
    "메뉴추천",
    "맛집",
    "연애",
    "데이트",
    "주식",
    "코인",
    "단타",
    "운동루틴",
    "게임공략",
]

HISTORY_QUERY_HINTS = [
    "누구",
    "뭐야",
    "무엇",
    "어떤",
    "사람",
    "인물",
    "일화",
    "사건",
    "시대",
    "자료",
    "사료",
    "기록",
    "설명",
    "알려줘",
    "찾아줘",
]


def normalize_topic_text(text: str) -> str:
    return text.lower().replace(" ", "").replace("\n", "")


def contains_any(normalized_text: str, terms: list[str]) -> bool:
    return any(term.lower().replace(" ", "") in normalized_text for term in terms)


def is_history_topic(text: str) -> bool:
    return contains_any(normalize_topic_text(text), HISTORY_TOPIC_TERMS)


def assess_history_topic(text: str, strict: bool = False) -> TopicDecision:
    normalized = normalize_topic_text(text)
    if not normalized:
        return TopicDecision(status="deny", reason="empty")
    if is_history_topic(text):
        return TopicDecision(status="allow", reason="known_history_signal")
    if contains_any(normalized, OBVIOUS_OFF_TOPIC_TERMS):
        return TopicDecision(status="deny", reason="obvious_off_topic_signal")
    if not strict and contains_any(normalized, HISTORY_QUERY_HINTS):
        return TopicDecision(status="unknown", reason="entity_or_source_lookup_needed")
    return TopicDecision(status="deny", reason="no_history_signal")
