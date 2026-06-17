from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.schemas.ai import AgentChatPageContext, AgentRunResponse, AgentStep
from app.services.ai_runtime import run_agent
from app.services.safety import agent_response_from_safety, moderate_input


class ChatAgentState(TypedDict, total=False):
    message: str
    page_context: dict[str, Any] | None
    user_nickname: str
    goal: str
    topic: str
    graph_mode: str
    response: AgentRunResponse


@dataclass(frozen=True)
class ChatCapability:
    name: str
    description: str
    matches: Callable[[str], bool]
    handle: Callable[[Session, Settings, str, AgentChatPageContext | None, User], AgentRunResponse]


def run_chat_agent(
    db: Session,
    settings: Settings,
    message: str,
    page_context: AgentChatPageContext | None,
    current_user: User,
) -> AgentRunResponse:
    safety_response = agent_response_from_safety(moderate_input(message, surface="chat", require_history_topic=False))
    if safety_response is not None:
        return safety_response

    routed_response = _route_chat_capability(db, settings, message, page_context, current_user)
    if routed_response is not None:
        return routed_response

    topic_check_text = "\n".join(
        part
        for part in [
            message,
            page_context.post_title if page_context else "",
            page_context.post_summary if page_context else "",
        ]
        if part
    )
    safety_response = agent_response_from_safety(moderate_input(topic_check_text, surface="chat"))
    if safety_response is not None:
        return safety_response

    initial_state: ChatAgentState = {
        "message": message.strip(),
        "page_context": page_context.model_dump() if page_context else None,
        "user_nickname": current_user.nickname,
        "graph_mode": "langgraph",
    }

    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(ChatAgentState)
        graph.add_node("prepare_context", _prepare_context_node)
        graph.add_node("run_retrieval_agent", lambda state: _run_retrieval_agent_node(state, db, settings))
        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "run_retrieval_agent")
        graph.add_edge("run_retrieval_agent", END)
        result = graph.compile().invoke(initial_state)
    except ImportError:
        fallback_state: ChatAgentState = {**initial_state, "graph_mode": "local_fallback"}
        prepared = {**fallback_state, **_prepare_context_node(fallback_state)}
        result = {**prepared, **_run_retrieval_agent_node(prepared, db, settings)}

    return result["response"]


MY_POSTS_TERMS = ["내글", "내게시물", "내게시글", "내가쓴글", "작성한글"]
MY_COMMENTS_TERMS = ["내댓글", "내가쓴댓글", "작성한댓글"]
POST_SEARCH_INTENT_TERMS = ["게시물", "게시글", "포스트", "글"]
POST_SEARCH_ACTION_TERMS = ["찾아", "검색", "보여", "알려", "추천"]
POST_SEARCH_STOP_WORDS = [
    "게시물을",
    "게시물",
    "게시글을",
    "게시글",
    "포스트를",
    "포스트",
    "글을",
    "글",
    "찾아줘",
    "찾아",
    "검색해줘",
    "검색",
    "보여줘",
    "보여",
    "알려줘",
    "알려",
    "추천해줘",
    "추천",
    "대한",
    "관련된",
    "관련",
    "있는",
    "좀",
]


CHAT_CAPABILITIES = [
    ChatCapability(
        name="user.my_posts",
        description="현재 로그인 사용자가 작성한 최근 게시글을 조회합니다.",
        matches=lambda normalized: any(term in normalized for term in MY_POSTS_TERMS),
        handle=lambda db, settings, message, page_context, current_user: _answer_my_posts(db, current_user),
    ),
    ChatCapability(
        name="user.my_comments",
        description="현재 로그인 사용자가 작성한 최근 댓글을 조회합니다.",
        matches=lambda normalized: any(term in normalized for term in MY_COMMENTS_TERMS),
        handle=lambda db, settings, message, page_context, current_user: _answer_my_comments(db, current_user),
    ),
    ChatCapability(
        name="post.search",
        description="게시판 posts 테이블에서 제목/본문 기준으로 실제 게시글을 검색합니다.",
        matches=lambda normalized: _is_post_search_request(normalized),
        handle=lambda db, settings, message, page_context, current_user: _answer_post_search(db, message),
    ),
]


def _route_chat_capability(
    db: Session,
    settings: Settings,
    message: str,
    page_context: AgentChatPageContext | None,
    current_user: User,
) -> AgentRunResponse | None:
    normalized = _normalize_intent_text(message)
    for capability in CHAT_CAPABILITIES:
        if capability.matches(normalized):
            response = capability.handle(db, settings, message, page_context, current_user)
            return response.model_copy(
                update={
                    "steps": [
                        AgentStep(
                            name="intent.route",
                            output=f"`{capability.name}` capability를 선택했습니다. {capability.description}",
                        ),
                        *response.steps,
                    ]
                }
            )
    return None


def _answer_post_search(db: Session, message: str) -> AgentRunResponse:

    query = _extract_post_search_query(message)
    if not query:
        return AgentRunResponse(
            steps=[AgentStep(name="post.search", output="게시물 검색 의도를 감지했지만 검색어가 부족해 DB 검색을 실행하지 않았습니다.")],
            final_answer="어떤 주제의 게시물을 찾을지 검색어를 함께 입력해 주세요. 예: `광해군 관련 게시물 찾아줘`",
            tool_logs=[],
        )

    posts = _search_posts(db, query)
    if not posts:
        return AgentRunResponse(
            steps=[AgentStep(name="post.search", output=f"posts 테이블에서 `{query}` 검색 결과 0건을 확인했습니다.")],
            final_answer=(
                f"현재 게시판에는 **{query}** 관련 게시물이 없습니다.\n\n"
                "원하면 같은 키워드로 역사 자료나 외부 사료 검색을 도와드릴 수 있습니다."
            ),
            tool_logs=[],
        )

    lines = [f"**{query}** 관련 게시물을 {len(posts)}건 찾았습니다.\n"]
    for index, post in enumerate(posts, start=1):
        tags = ", ".join(f"#{tag.name}" for tag in post.tags)
        tag_text = f"\n   - 태그: {tags}" if tags else ""
        lines.append(
            f"{index}. [**{post.title}**](/posts/{post.id})\n"
            f"   - 작성자: {post.author.nickname}\n"
            f"   - 분류: {post.post_type} · {post.category}\n"
            f"   - 댓글 {post.comment_count} · 조회 {post.view_count}{tag_text}"
        )

    return AgentRunResponse(
        steps=[AgentStep(name="post.search", output=f"posts 테이블에서 `{query}` 검색 결과 {len(posts)}건을 반환했습니다.")],
        final_answer="\n\n".join(lines),
        tool_logs=[],
    )


def _answer_my_posts(db: Session, current_user: User) -> AgentRunResponse:
    posts = list(
        db.scalars(
            select(Post)
            .options(selectinload(Post.tags), selectinload(Post.author))
            .where(Post.author_id == current_user.id)
            .order_by(Post.created_at.desc())
            .limit(5)
        ).all()
    )
    if not posts:
        return AgentRunResponse(
            steps=[AgentStep(name="user.my_posts", output="현재 사용자의 게시글 검색 결과 0건을 확인했습니다.")],
            final_answer="아직 작성한 게시글이 없습니다.",
            tool_logs=[],
        )

    lines = ["최근 작성한 게시글입니다.\n"]
    for index, post in enumerate(posts, start=1):
        lines.append(
            f"{index}. [**{post.title}**](/posts/{post.id})\n"
            f"   - 분류: {post.post_type} · {post.category}\n"
            f"   - 댓글 {post.comment_count} · 조회 {post.view_count}"
        )
    return AgentRunResponse(
        steps=[AgentStep(name="user.my_posts", output=f"현재 사용자의 최근 게시글 {len(posts)}건을 반환했습니다.")],
        final_answer="\n\n".join(lines),
        tool_logs=[],
    )


def _answer_my_comments(db: Session, current_user: User) -> AgentRunResponse:
    rows = list(
        db.execute(
            select(Comment, Post)
            .join(Post, Post.id == Comment.post_id)
            .where(Comment.author_id == current_user.id)
            .order_by(Comment.created_at.desc())
            .limit(5)
        ).all()
    )
    if not rows:
        return AgentRunResponse(
            steps=[AgentStep(name="user.my_comments", output="현재 사용자의 댓글 검색 결과 0건을 확인했습니다.")],
            final_answer="아직 작성한 댓글이 없습니다.",
            tool_logs=[],
        )

    lines = ["최근 작성한 댓글입니다.\n"]
    for index, (comment, post) in enumerate(rows, start=1):
        excerpt = re.sub(r"\s+", " ", comment.content).strip()[:80]
        lines.append(
            f"{index}. [**{post.title}**](/posts/{post.id})\n"
            f"   - 댓글: {excerpt}"
        )
    return AgentRunResponse(
        steps=[AgentStep(name="user.my_comments", output=f"현재 사용자의 최근 댓글 {len(rows)}건을 반환했습니다.")],
        final_answer="\n\n".join(lines),
        tool_logs=[],
    )


def _is_post_search_request(normalized: str) -> bool:
    has_post_term = any(term in normalized for term in POST_SEARCH_INTENT_TERMS)
    has_action_term = any(term in normalized for term in POST_SEARCH_ACTION_TERMS)
    return has_post_term and has_action_term


def _extract_post_search_query(message: str) -> str:
    query = message.strip()
    for word in POST_SEARCH_STOP_WORDS:
        query = query.replace(word, " ")
    query = re.sub(r"[^\w가-힣\s]", " ", query)
    tokens = []
    for token in query.split():
        tokens.append(re.sub(r"(에|에게|에서|으로|로|을|를|은|는|이|가|의)$", "", token))
    query = " ".join(token for token in tokens if token)
    return query[:80]


def _normalize_intent_text(message: str) -> str:
    return re.sub(r"\s+", "", message)


def _search_posts(db: Session, query: str) -> list[Post]:
    pattern = f"%{query}%"
    return list(
        db.scalars(
            select(Post)
            .options(selectinload(Post.author), selectinload(Post.tags))
            .where(or_(Post.title.ilike(pattern), Post.content.ilike(pattern)))
            .order_by(Post.created_at.desc())
            .limit(5)
        ).all()
    )


def _prepare_context_node(state: ChatAgentState) -> ChatAgentState:
    context = state.get("page_context") or {}
    message = state["message"]
    parts = [
        f"사용자: {state.get('user_nickname', '로그인 사용자')}",
        f"현재 화면: {context.get('path') or '알 수 없음'}",
    ]
    if context.get("post_id"):
        parts.append(f"게시글 ID: {context['post_id']}")
    if context.get("post_title"):
        parts.append(f"게시글 제목: {context['post_title']}")
    if context.get("post_summary"):
        parts.append(f"게시글 검색 요약: {context['post_summary']}")
    parts.append(f"사용자 질문: {message}")

    return {
        "goal": "역사 커뮤니티 챗봇 답변",
        "topic": "\n".join(parts),
    }


def _run_retrieval_agent_node(
    state: ChatAgentState,
    db: Session,
    settings: Settings,
) -> ChatAgentState:
    response = run_agent(db, settings, state["goal"], state["topic"])
    if state.get("graph_mode") == "langgraph":
        graph_output = "prepare_context -> run_retrieval_agent 순서로 챗봇 요청을 처리했습니다."
    else:
        graph_output = "LangGraph 패키지가 없는 환경이라 같은 노드 순서를 로컬 fallback으로 처리했습니다."

    return {
        "response": AgentRunResponse(
            steps=[
                AgentStep(name="langgraph.chat", output=graph_output),
                *response.steps,
            ],
            final_answer=response.final_answer,
            tool_logs=response.tool_logs,
        )
    }
