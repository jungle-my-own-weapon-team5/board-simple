import json
from typing import Any, Literal

from app.mcp.tools import search_posts, session_scope
from app.schemas.agent import (
    AgentChatContext,
    AgentChatRequest,
    AgentChatResponse,
    AgentPendingAction,
    AgentSource,
    AgentWorkflowStep,
)
from app.services import posts as post_service
from app.services.agent.models import AgentActionPlan
from app.services.agent.presenter import sources_from_result


def pending_action_tags(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, str):
        values = raw_tags.replace("#", "").replace(",", " ").split()
    elif isinstance(raw_tags, list):
        values = raw_tags
    else:
        values = []
    return [str(tag).strip().removeprefix("#").lower() for tag in values if str(tag).strip()]


def message_with_context(payload: AgentChatRequest) -> str:
    if payload.context is None:
        return payload.message

    context = payload.context
    context_payload = {
        "page": context.page,
        "post_id": context.post_id,
        "title": context.title,
        "content": context.content,
        "tags": context.tags,
    }
    return (
        f"{payload.message}\n\n"
        "Current editor/page context JSON:\n"
        f"{json.dumps(context_payload, ensure_ascii=False)}"
    )


def workflow_context_detail(context: AgentChatContext | None) -> str:
    if context is None:
        return "현재 페이지 문맥이 없어 일반 작성 목표로 처리했습니다."
    if context.page == "new_post":
        return "새 게시글 작성 문맥을 확인했습니다."
    if context.page == "edit_post":
        return "기존 게시글 수정 문맥을 확인했습니다."
    return "작성/수정 폼이 아닌 페이지 문맥을 확인했습니다."


def workflow_steps(
    *,
    searched_count: int,
    duplicate_count: int,
    context: AgentChatContext | None,
) -> list[AgentWorkflowStep]:
    duplicate_status: Literal["completed", "needs_confirmation"] = (
        "needs_confirmation" if duplicate_count > 0 else "completed"
    )
    return [
        AgentWorkflowStep(
            id="search_existing_posts",
            label="기존 글 검색",
            status="completed",
            detail=f"관련 게시글 {searched_count}개를 확인했습니다.",
        ),
        AgentWorkflowStep(
            id="check_duplicates",
            label="중복 검사",
            status=duplicate_status,
            detail=(
                f"중복 의심 후보 {duplicate_count}개가 있습니다."
                if duplicate_count > 0
                else "중복 의심 후보가 없습니다."
            ),
        ),
        AgentWorkflowStep(
            id="prepare_post_draft",
            label="초안 생성",
            status="completed",
            detail=workflow_context_detail(context),
        ),
        AgentWorkflowStep(
            id="suggest_thumbnail",
            label="썸네일 제안",
            status="pending",
            detail="초안을 적용한 뒤 Generate thumbnail 버튼으로 생성할 수 있습니다.",
        ),
        AgentWorkflowStep(
            id="apply_to_editor",
            label="폼 적용",
            status="needs_confirmation",
            detail="사용자 확인 후 제목, 본문, 태그를 폼에 적용합니다.",
        ),
    ]


def execute_post_workflow(plan: AgentActionPlan, context: AgentChatContext | None) -> AgentChatResponse:
    title = str(plan.args.get("title", "")).strip()
    content = str(plan.args.get("content", "")).strip()
    tags = pending_action_tags(plan.args.get("tags", []))
    search_query = str(
        plan.args.get("search_query")
        or plan.args.get("q")
        or plan.args.get("topic")
        or title
        or ""
    ).strip()

    search_result = search_posts(q=search_query or None, page=1, size=5)
    sources = sources_from_result("search_posts", search_result)

    exclude_post_id = context.post_id if context and context.page == "edit_post" else None
    with session_scope() as db:
        duplicate_candidates = post_service.check_duplicate_posts(
            db,
            title=title,
            content=content,
            tags=tags,
            exclude_post_id=exclude_post_id,
        )

    for candidate in duplicate_candidates:
        sources.append(
            AgentSource(
                post_id=candidate.id,
                title=candidate.title,
                snippet=candidate.snippet,
            )
        )

    pending_action = AgentPendingAction(
        type="apply_post_draft",
        title=title,
        content=content,
        tags=tags,
    )
    duplicate_count = len(duplicate_candidates)
    answer = (
        "기존 글 검색과 중복 검사를 마치고 초안을 준비했습니다. "
        "중복 의심 후보를 확인한 뒤 초안을 적용할지 선택해주세요."
        if duplicate_count > 0
        else "기존 글 검색과 중복 검사를 마치고 초안을 준비했습니다. 초안을 적용할까요?"
    )
    return AgentChatResponse(
        answer=answer,
        sources=sources,
        steps=workflow_steps(
            searched_count=search_result.total,
            duplicate_count=duplicate_count,
            context=context,
        ),
        pending_action=pending_action,
    )
