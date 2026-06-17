from app.schemas.ai import (
    AgentRunResponse,
    AgentStep,
    DiscussionTopic,
    ExternalResource,
    ExternalSearchResponse,
    RagCitation,
    RagSearchResponse,
    ToolLog,
)

SEED_CITATIONS = [
    RagCitation(
        id="rag-sejo-danjong-001",
        title="계유정난과 왕권 재편",
        period="조선 전기",
        summary="세조와 단종을 둘러싼 권력 재편은 안정론과 찬탈론이 함께 논의되는 대표 주제입니다.",
        relevance=0.91,
        source_url="https://sillok.history.go.kr",
    ),
    RagCitation(
        id="rag-hunminjeongeum-001",
        title="훈민정음 창제와 정치적 맥락",
        period="세종",
        summary="훈민정음은 애민정신뿐 아니라 지식과 행정 체계의 변화라는 관점에서도 해석할 수 있습니다.",
        relevance=0.84,
        source_url="https://sillok.history.go.kr",
    ),
    RagCitation(
        id="rag-faction-001",
        title="붕당 정치의 논쟁 구조",
        period="조선 중기",
        summary="붕당은 단순한 당파 싸움이 아니라 사림 정치의 공론 구조와도 연결됩니다.",
        relevance=0.78,
        source_url="https://sillok.history.go.kr",
    ),
]


def get_discussion_topics() -> list[DiscussionTopic]:
    return [
        DiscussionTopic(
            source="오늘 꺼내볼 기록",
            title="세조의 왕위 찬탈, 결과가 좋으면 정당화될 수 있을까?",
            summary="조선 초기 권력 재편을 두고 안정과 명분 중 무엇을 더 크게 볼지 묻는 주제입니다.",
            question="조선의 안정이라는 결과가 단종 폐위를 정당화할 수 있을까요?",
            reason="세조, 단종, 계유정난은 댓글 의견이 자연스럽게 갈리는 대표 토론 주제입니다.",
            tags=["세조", "단종", "계유정난", "왕권"],
        ),
        DiscussionTopic(
            source="요즘 뜨는 주제",
            title="문종은 짧은 재위 때문에 과소평가된 왕일까?",
            summary="짧은 재위와 건강 문제 때문에 업적 평가가 덜 드러난 왕을 다시 보는 카드입니다.",
            question="문종을 세종의 그림자가 아니라 독립적인 군주로 평가할 수 있을까요?",
            reason="인물 재평가는 가볍게 읽히면서도 근거 확인으로 이어지기 좋습니다.",
            tags=["문종", "세종", "왕평가"],
        ),
        DiscussionTopic(
            source="게시판 반응",
            title="훈민정음 창제는 애민정신만으로 설명할 수 있을까?",
            summary="익숙한 주제를 정치, 행정, 지식 보급의 관점으로 넓혀 보는 토론거리입니다.",
            question="문자 창제가 백성 사랑과 국가 운영 전략 중 어디에 더 가까웠을까요?",
            reason="친숙한 소재라 새 사용자가 첫 댓글을 달기 쉽습니다.",
            tags=["세종", "훈민정음", "문화"],
        ),
    ]


def search_rag(query: str, top_k: int) -> RagSearchResponse:
    citations = SEED_CITATIONS[:top_k]
    return RagSearchResponse(
        answer_summary="내부 seed 자료 기준으로 직접 결론을 단정하기보다, 관련 근거와 해석 지점을 나눠 보는 것이 적절합니다.",
        citations=citations,
        weak_evidence=False,
    )


def search_external(keyword: str) -> ExternalSearchResponse:
    return ExternalSearchResponse(
        resources=[
            ExternalResource(
                title=f"{keyword} 관련 외부 사료 검색",
                provider="국사편찬위원회 조선왕조실록",
                url="https://sillok.history.go.kr",
                description="MCP 외부 호출 자리에 연결할 대표 공개 사료 서비스입니다. 현재는 데모 응답입니다.",
            )
        ],
        tool_log=ToolLog(
            tool="mcp.external_history_search",
            input=keyword,
            status="demo",
            elapsed_ms=42,
        ),
    )


def run_agent(goal: str, topic: str) -> AgentRunResponse:
    return AgentRunResponse(
        steps=[
            AgentStep(name="intent", output=f"목표 `{goal}`에 맞춰 `{topic}` 자료 확인이 필요합니다."),
            AgentStep(name="rag.search", output="내부 seed 근거 3건을 조회했습니다."),
            AgentStep(name="mcp.external_search", output="외부 사료 서비스 후보 1건을 확인했습니다."),
        ],
        final_answer="근거가 있는 내용은 citation으로 분리하고, 해석이 갈리는 부분은 댓글 토론 질문으로 넘기는 흐름을 추천합니다.",
        tool_logs=[
            ToolLog(tool="rag.search", input=topic, status="ok", elapsed_ms=31),
            ToolLog(tool="mcp.external_history_search", input=topic, status="demo", elapsed_ms=42),
        ],
    )
