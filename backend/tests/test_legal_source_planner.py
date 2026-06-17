from app.core.config import Settings
from app.services.ai.errors import ProviderUnavailableError
from app.services.ai.types import AITextRequest, AITextResult
from app.services.rag.legal_source_planner import plan_legal_source_candidates


def test_planner_parses_llm_json_candidates() -> None:
    ai_client = _PlanningAIClient(
        text=(
            '{"candidates":[{"document_type":"statute",'
            '"title":"주택임대차보호법","query":"주택임대차보호법",'
            '"reason":"임대차 보증금 반환 쟁점"}]}'
        )
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="임대차 계약이 종료되었지만 보증금을 돌려받지 못했습니다.",
        question="검토할 법령을 찾아주세요.",
        search_mode="focused_answer",
    )

    assert plan.candidates[0].title == "주택임대차보호법"
    assert {candidate.title for candidate in plan.candidates} >= {
        "주택임대차보호법",
        "민법",
    }
    assert plan.candidates[0].query == "주택임대차보호법"
    assert ai_client.requests[0].model == "planner-test-model"
    assert ai_client.requests[0].metadata == {"purpose": "legal_source_planner"}


def test_planner_parses_issue_queries() -> None:
    ai_client = _PlanningAIClient(
        text=(
            '{"issues":[{"issue_key":"corpse_concealment",'
            '"title":"corpse concealment",'
            '"description":"concealing a body after death",'
            '"domain":"criminal",'
            '"facts_slice":"A buried the body after the death.",'
            '"internal_rag_query":"corpse abandonment concealment criminal act",'
            '"official_source_query":"Criminal Act",'
            '"official_source_candidates":[{"document_type":"statute",'
            '"title":"Criminal Act","query":"Criminal Act",'
            '"reason":"criminal liability issue"}]}]}'
        )
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="A killed B by mistake and buried the body.",
        question="Find the legal issues.",
        search_mode="issue_spotting",
    )

    assert len(plan.issues) == 1
    assert plan.issues[0].issue_key == "corpse_concealment"
    assert plan.issues[0].domain == "criminal"
    assert plan.issues[0].facts_slice == "A buried the body after the death."
    assert plan.issues[0].internal_rag_query == (
        "corpse abandonment concealment criminal act"
    )
    assert [candidate.query for candidate in plan.candidates] == ["Criminal Act"]
    assert '"domain"' in ai_client.requests[0].prompt
    assert '"facts_slice"' in ai_client.requests[0].prompt


def test_planner_parses_expected_article_refs() -> None:
    ai_client = _PlanningAIClient(
        text=(
            '{"issues":[{"issue_key":"surrender",'
            '"title":"자수","internal_rag_query":"형법 자수",'
            '"expected_article_refs":[{"law_title":"형법",'
            '"article_no":"제 52 조","article_title":"자수ㆍ자복",'
            '"reason":"자수 감경 확인"}],'
            '"official_source_candidates":[{"document_type":"statute",'
            '"title":"형법","query":"형법"}]}]}'
        )
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="A가 경찰서에 가서 자수했습니다.",
        question="쟁점을 알려주세요.",
        search_mode="issue_spotting",
    )

    surrender_issue = next(issue for issue in plan.issues if issue.issue_key == "surrender")
    assert surrender_issue.expected_article_refs[0].law_title == "형법"
    assert surrender_issue.expected_article_refs[0].article_no == "제52조"


def test_planner_augments_required_criminal_issue_hints_for_reviewer() -> None:
    ai_client = _PlanningAIClient(
        text='{"issues":[],"candidates":[]}'
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts=(
            "A는 실수로 B를 죽였고 시체를 비닐백에 담아 야산에 매장했습니다. "
            "1주일 뒤 경찰서에 가서 자수했지만 시체를 찾지 못했습니다."
        ),
        question="검토할 쟁점을 알려주세요.",
        search_mode="issue_spotting",
    )

    criminal_issues = [
        issue for issue in plan.issues if issue.issue_key.startswith("criminal_")
    ]
    assert criminal_issues
    assert all(issue.domain == "criminal" for issue in criminal_issues)
    assert any(issue.expected_article_refs for issue in criminal_issues)
    assert all("제" not in issue.internal_rag_query for issue in plan.issues)
    assert {candidate.title for candidate in plan.candidates} >= {"형법", "형사소송법"}
    assert "required_issue_hint" in {candidate.reason for candidate in plan.candidates}


def test_planner_prioritizes_required_criminal_candidates_before_llm_noise() -> None:
    ai_client = _PlanningAIClient(
        text=(
            '{"candidates":[{"document_type":"statute",'
            '"title":"군에서의 형의 집행 및 군수용자의 처우에 관한 법률",'
            '"query":"군에서의 형의 집행 및 군수용자의 처우에 관한 법률"}]}'
        )
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts=(
            "A는 실수로 B를 죽였고 시체를 비닐백에 담아 야산에 매장했습니다. "
            "1주일 뒤 경찰서에 가서 자수했지만 시체를 찾지 못했습니다."
        ),
        question="검토할 쟁점을 알려주세요.",
        search_mode="issue_spotting",
    )

    assert [candidate.title for candidate in plan.candidates[:2]] == [
        "형법",
        "형사소송법",
    ]


def test_planner_augments_investment_case_with_multi_domain_issue_hints() -> None:
    ai_client = _PlanningAIClient(text='{"issues":[],"candidates":[]}')

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts=(
            "A는 B에게 좋은 투자처가 있다고 말하고 연 수익률 50%를 보장한다고 이야기한 뒤 "
            "1억원을 받았습니다. A는 일부를 C에게 투자했고 D가 이를 편취하고 달아났으며, "
            "A는 나머지 금액을 다른 사업에 투자해 수익을 냈습니다. "
            "A는 7500만원만 돌려주고 500만원을 보수로 갖겠다고 했습니다."
        ),
        question="검토해야 할 쟁점과 답변 초안 방향을 알려주세요.",
        search_mode="issue_spotting",
    )

    issue_keys = {issue.issue_key for issue in plan.issues}
    assert issue_keys >= {
        "civil_contract_breach_investment",
        "civil_mandate_accounting_investment",
        "criminal_fraud_investment",
        "financial_regulation_guaranteed_return",
    }
    assert {issue.domain for issue in plan.issues} >= {
        "civil",
        "criminal",
        "financial_regulation",
    }
    assert [candidate.title for candidate in plan.candidates] == [
        "민법",
        "형법",
        "유사수신행위의 규제에 관한 법률",
        "자본시장과 금융투자업에 관한 법률",
        "이자제한법",
    ]
    assert any(
        ref.law_title == "형법" and ref.article_no == "제347조"
        for issue in plan.issues
        for ref in issue.expected_article_refs
    )
    assert any(
        ref.law_title == "민법" and ref.article_no == "제390조"
        for issue in plan.issues
        for ref in issue.expected_article_refs
    )
    assert all("제347조" not in issue.internal_rag_query for issue in plan.issues)


def test_planner_ignores_unsupported_document_types() -> None:
    ai_client = _PlanningAIClient(
        text=(
            '{"candidates":[{"document_type":"case",'
            '"title":"대법원 판례","query":"대법원 판례"}]}'
        )
    )

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="사기 피해를 당했습니다.",
        question="형법상 쟁점을 검토해주세요.",
        search_mode="issue_spotting",
    )

    assert [candidate.title for candidate in plan.candidates] == ["형법"]
    assert plan.candidates[0].reason == "explicit_or_known_statute_fallback"


def test_planner_falls_back_to_raw_query_when_llm_returns_invalid_json() -> None:
    ai_client = _PlanningAIClient(text="not json")

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="The tenant paid a deposit and the landlord refuses repayment.",
        question="Find the relevant Korean statute.",
        search_mode="focused_answer",
    )

    assert len(plan.candidates) == 1
    assert plan.candidates[0].query == "Find the relevant Korean statute."
    assert plan.candidates[0].reason == "raw_query_fallback"


def test_planner_uses_fallback_when_planner_model_is_not_configured() -> None:
    ai_client = _PlanningAIClient(text="should not be used")

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(ai_agent_model=""),
        facts="형법상 사기죄가 문제될 수 있습니다.",
        question="관련 법령을 찾아주세요.",
        search_mode="focused_answer",
    )

    assert [candidate.title for candidate in plan.candidates] == ["형법"]
    assert ai_client.requests == []


def test_planner_falls_back_when_provider_fails() -> None:
    ai_client = _FailingPlanningAIClient()

    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=_settings(),
        facts="형법상 사기죄가 문제될 수 있습니다.",
        question="관련 법령을 찾아주세요.",
        search_mode="focused_answer",
    )

    assert [candidate.title for candidate in plan.candidates] == ["형법"]
    assert len(ai_client.requests) == 1


def _settings(*, ai_agent_model: str = "planner-test-model") -> Settings:
    return Settings(
        app_env="test",
        ai_rag_enabled=False,
        ai_agent_provider="mock",
        ai_agent_model=ai_agent_model,
        ai_source_planner_model=ai_agent_model,
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
    )


class _PlanningAIClient:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.requests: list[AITextRequest] = []

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self.requests.append(request)
        return AITextResult(
            text=self.text,
            agent_provider="mock",
            agent_model_name=request.model,
            finish_reason="stop",
            raw_response_id="planner-test-response",
        )


class _FailingPlanningAIClient:
    def __init__(self) -> None:
        self.requests: list[AITextRequest] = []

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self.requests.append(request)
        raise ProviderUnavailableError("planner unavailable")
