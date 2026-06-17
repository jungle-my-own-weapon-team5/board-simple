from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.ai import AgentRunResponse, AgentStep, EditorAgentResponse
from app.services.topic_guard import assess_history_topic, is_history_topic

SafetyCategory = Literal[
    "none",
    "self_harm",
    "violence",
    "sexual",
    "hate",
    "privacy",
    "illegal",
    "high_stakes",
    "off_topic",
]
SafetyAction = Literal["allow", "allow_with_caution", "refuse", "safe_redirect", "off_topic"]
SafetySurface = Literal["chat", "editor", "post", "agent", "thumbnail"]


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    category: SafetyCategory
    action: SafetyAction
    message: str | None = None
    step_name: str = "safety.allow"
    log_output: str = "안전 검수를 통과했습니다."


SELF_HARM_RESPONSE = (
    "이 질문에는 조심스럽게 답하겠습니다. 자살은 매우 심각한 주제이고, 저는 자살을 권하거나 미화할 수 없습니다. "
    "대신 지금 고통을 겪는 사람에게는 혼자 버티지 말고 주변 사람이나 전문가, 긴급 도움을 바로 연결하는 것이 중요합니다.\n\n"
    "만약 이 질문이 본인이나 가까운 사람의 현재 상황과 관련된 것이라면 지금 바로 도움을 요청해 주세요. "
    "급박한 위험이 있으면 112 또는 119에 연락하세요. 한국에서는 자살예방상담전화 109로 바로 상담할 수 있습니다. "
    "믿을 수 있는 가족, 친구, 학교나 직장 상담창구에 지금 상태를 알리는 것도 좋습니다.\n\n"
    "원하면 제가 지금 바로 짧은 위로 문구, 주변 사람에게 보내는 연락문, 도움 요청 방법 중 하나로 정리해드릴 수 있습니다."
)

OFF_TOPIC_RESPONSE = (
    "이 서비스는 역사, 특히 조선시대 인물·사건·문화·사료를 다루는 커뮤니티입니다. "
    "현재 요청은 게시판 성격과 직접 관련된 역사 주제로 보기 어려워 처리하지 않았습니다. "
    "역사 인물, 사건, 시대, 사료, 문화사와 연결해서 다시 작성해 주세요."
)

POST_OFF_TOPIC_MESSAGE = (
    "이 게시판은 역사, 특히 조선시대 인물·사건·문화·사료를 다루는 공간입니다. "
    "제목이나 본문에 역사 주제가 충분히 드러나지 않아 게시할 수 없습니다."
)

REFUSAL_MESSAGES: dict[SafetyCategory, str] = {
    "violence": "폭력, 살해, 테러, 무기 제작처럼 사람을 해치거나 위험을 키울 수 있는 요청은 처리할 수 없습니다.",
    "sexual": "성적 행위 묘사나 성적 만족을 목적으로 한 요청은 이 게시판에서 처리할 수 없습니다.",
    "hate": "특정 집단에 대한 혐오, 비하, 차별을 조장하는 내용은 처리할 수 없습니다.",
    "privacy": "개인정보를 찾거나 노출하거나 추적하는 요청은 처리할 수 없습니다.",
    "illegal": "해킹, 사기, 마약, 불법 우회처럼 불법행위를 돕는 요청은 처리할 수 없습니다.",
    "high_stakes": "의학, 법률, 금융 판단을 대신하는 고위험 조언은 제공하지 않습니다. 역사적 맥락의 질문으로 범위를 좁혀 주세요.",
    "off_topic": OFF_TOPIC_RESPONSE,
    "self_harm": SELF_HARM_RESPONSE,
    "none": "",
}

SELF_HARM_TERMS = ["자살", "극단적선택", "죽고싶", "살기싫", "목숨을끊", "생을마감", "suicide", "killmyself"]
SELF_HARM_IMMINENT_TERMS = ["내가", "나", "저", "지금", "오늘", "방법", "어떻게", "하고싶", "할래", "죽고싶"]
VIOLENCE_TERMS = ["죽이는법", "살해", "테러", "폭탄", "총기제작", "칼로찌", "해치는법", "무기만드는법"]
SEXUAL_TERMS = ["야한", "성관계", "성적묘사", "포르노", "누드", "미성년자성"]
HATE_TERMS = ["죽어야한다", "열등한민족", "혐오", "장애인비하", "인종차별"]
PRIVACY_TERMS = ["전화번호찾아", "주소찾아", "신상털", "개인정보", "주민등록번호", "계정비번"]
ILLEGAL_TERMS = ["해킹", "피싱", "사기치는법", "마약제조", "몰래접속", "비밀번호뚫"]
HIGH_STAKES_TERMS = ["주식추천", "코인추천", "진단해줘", "처방해줘", "고소하면이겨", "세금회피"]
EDUCATIONAL_CONTEXT_TERMS = ["역사", "사료", "설명", "평가", "문화", "제도", "기록", "사례", "맥락", "토론"]
DANGEROUS_INTENT_TERMS = [
    "만드는법",
    "제작법",
    "제조법",
    "하는법",
    "알려줘",
    "뚫",
    "몰래",
    "찾아줘",
    "추적",
    "공격",
]


def normalize_safety_text(text: str) -> str:
    return text.lower().replace(" ", "").replace("\n", "")


def contains_any(normalized_text: str, terms: list[str]) -> bool:
    return any(term.lower().replace(" ", "") in normalized_text for term in terms)


def has_educational_history_context(text: str) -> bool:
    normalized = normalize_safety_text(text)
    return is_history_topic(text) and contains_any(normalized, EDUCATIONAL_CONTEXT_TERMS)


def has_dangerous_intent(normalized_text: str) -> bool:
    return contains_any(normalized_text, DANGEROUS_INTENT_TERMS)


def classify_sensitive_category(text: str) -> SafetyCategory:
    normalized = normalize_safety_text(text)
    if contains_any(normalized, SELF_HARM_TERMS):
        if has_educational_history_context(text) and not contains_any(normalized, SELF_HARM_IMMINENT_TERMS):
            return "none"
        return "self_harm"
    category_terms: list[tuple[SafetyCategory, list[str]]] = [
        ("violence", VIOLENCE_TERMS),
        ("sexual", SEXUAL_TERMS),
        ("hate", HATE_TERMS),
        ("privacy", PRIVACY_TERMS),
        ("illegal", ILLEGAL_TERMS),
        ("high_stakes", HIGH_STAKES_TERMS),
    ]
    for category, terms in category_terms:
        if contains_any(normalized, terms):
            if has_educational_history_context(text) and not has_dangerous_intent(normalized):
                return "none"
            return category
    return "none"


def moderate_input(text: str, surface: SafetySurface = "chat", require_history_topic: bool = True) -> SafetyDecision:
    category = classify_sensitive_category(text)
    if category == "self_harm":
        return SafetyDecision(
            allowed=False,
            category=category,
            action="safe_redirect",
            message=SELF_HARM_RESPONSE,
            step_name="safety.self_harm",
            log_output="자살/자해 관련 표현을 감지해 RAG, 외부 검색, LLM 생성을 건너뛰고 안전 응답을 반환했습니다.",
        )
    if category != "none":
        return SafetyDecision(
            allowed=False,
            category=category,
            action="refuse",
            message=REFUSAL_MESSAGES[category],
            step_name=f"safety.{category}",
            log_output=f"유해·민감 정보 카테고리 `{category}`를 감지해 처리를 중단했습니다.",
        )
    if require_history_topic:
        topic_decision = assess_history_topic(text, strict=surface in {"post", "thumbnail"})
        if topic_decision.status == "allow":
            return SafetyDecision(allowed=True, category="none", action="allow")
        if topic_decision.status == "unknown":
            return SafetyDecision(
                allowed=True,
                category="none",
                action="allow_with_caution",
                log_output="역사성은 아직 확정되지 않았지만 인물·사건·자료형 질문으로 판단해 RAG/외부 검색으로 확인합니다.",
            )
        message = POST_OFF_TOPIC_MESSAGE if surface == "post" else OFF_TOPIC_RESPONSE
        return SafetyDecision(
            allowed=False,
            category="off_topic",
            action="off_topic",
            message=message,
            step_name="safety.off_topic",
            log_output=f"게시판 주제와 직접 관련된 역사 신호가 부족해 처리를 중단했습니다. reason={topic_decision.reason}",
        )
    return SafetyDecision(allowed=True, category="none", action="allow")


def off_topic_message_for(text: str) -> str | None:
    decision = moderate_input(text, surface="chat", require_history_topic=True)
    if decision.category == "off_topic":
        return decision.message
    return None


def post_off_topic_message_for(title: str, content: str, tags: list[str] | None = None) -> str | None:
    text = "\n".join([title, content, " ".join(tags or [])])
    decision = moderate_input(text, surface="post", require_history_topic=True)
    if decision.category == "off_topic":
        return decision.message
    return None


def post_safety_message_for(title: str, content: str, tags: list[str] | None = None) -> str | None:
    text = "\n".join([title, content, " ".join(tags or [])])
    decision = moderate_input(text, surface="post", require_history_topic=True)
    return None if decision.allowed else decision.message


def self_harm_response_for(text: str) -> str | None:
    decision = moderate_input(text, surface="chat", require_history_topic=False)
    if decision.category == "self_harm":
        return decision.message
    return None


def agent_response_from_safety(decision: SafetyDecision) -> AgentRunResponse | None:
    if decision.allowed:
        return None
    return AgentRunResponse(
        steps=[AgentStep(name=decision.step_name, output=decision.log_output)],
        final_answer=decision.message or OFF_TOPIC_RESPONSE,
        tool_logs=[],
    )


def editor_response_from_safety(decision: SafetyDecision) -> EditorAgentResponse | None:
    if decision.allowed:
        return None
    return EditorAgentResponse(
        action="answer",
        agent_message=decision.message or OFF_TOPIC_RESPONSE,
        suggested_title=None,
        suggested_content=None,
        tags=[],
        category=None,
        questions=[],
        external_resources=[],
        tool_logs=[],
        agent_steps=[AgentStep(name=decision.step_name, output=decision.log_output)],
        evidence_summary=None,
        weak_evidence=False,
    )


def make_self_harm_agent_response(message: str) -> AgentRunResponse | None:
    decision = moderate_input(message, surface="chat", require_history_topic=False)
    if decision.category != "self_harm":
        return None
    return agent_response_from_safety(decision)


def make_off_topic_agent_response(message: str) -> AgentRunResponse | None:
    decision = moderate_input(message, surface="chat", require_history_topic=True)
    if decision.category == "self_harm":
        return None
    return agent_response_from_safety(decision)


def make_self_harm_editor_response(message: str) -> EditorAgentResponse | None:
    decision = moderate_input(message, surface="editor", require_history_topic=False)
    if decision.category != "self_harm":
        return None
    return editor_response_from_safety(decision)


def make_off_topic_editor_response(message: str) -> EditorAgentResponse | None:
    decision = moderate_input(message, surface="editor", require_history_topic=True)
    if decision.category == "self_harm":
        return None
    return editor_response_from_safety(decision)
