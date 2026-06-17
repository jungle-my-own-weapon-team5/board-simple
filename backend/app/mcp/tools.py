from __future__ import annotations

import os
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.fitlog import MealLog, StrategyAdvice
from app.schemas.fitlog import MealLogList, MealLogRead, StrategyAdviceList, StrategyAdviceRead
from app.services.fitlog import build_daily_report, create_strategy


MEAL_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}


def mcp_user_id() -> int:
    raw_value = os.environ.get("FITLOG_MCP_USER_ID")
    if not raw_value:
        raise ValueError("FITLOG_MCP_USER_ID is required for FitLog MCP tool calls")
    try:
        user_id = int(raw_value)
    except ValueError as exc:
        raise ValueError("FITLOG_MCP_USER_ID must be an integer") from exc
    if user_id <= 0:
        raise ValueError("FITLOG_MCP_USER_ID must be a positive integer")
    return user_id


def parse_date(value: Any, field_name: str = "date") -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a YYYY-MM-DD string") from exc


def dump_model(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def meal_sort_key(meal: MealLog) -> tuple[int, str, int]:
    return (MEAL_ORDER.get(meal.meal_type, 99), meal.meal_time or "", meal.id)


def get_daily_meals(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    target_date = parse_date(args.get("date"))
    user_id = mcp_user_id()
    meals = db.scalars(
        select(MealLog)
        .where(MealLog.user_id == user_id, MealLog.meal_date == target_date)
        .options(selectinload(MealLog.foods))
        .order_by(MealLog.id.asc())
    ).all()
    items = [MealLogRead.model_validate(meal) for meal in sorted(meals, key=meal_sort_key)]
    return dump_model(MealLogList(items=items))


def get_daily_report(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    target_date = parse_date(args.get("date"))
    return dump_model(build_daily_report(db, mcp_user_id(), target_date))


def get_strategy_history(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    user_id = mcp_user_id()
    target_date = parse_date(args["date"]) if args.get("date") is not None else None
    statement = select(StrategyAdvice).where(StrategyAdvice.user_id == user_id)
    if target_date is not None:
        statement = statement.where(StrategyAdvice.target_date == target_date)
    items = db.scalars(statement.order_by(StrategyAdvice.created_at.desc())).all()
    return dump_model(
        StrategyAdviceList(
            items=[
                StrategyAdviceRead(
                    id=item.id,
                    date=item.target_date,
                    question=item.question,
                    pace_status=item.pace_status,
                    summary=item.summary,
                    today_strategy=item.today_strategy,
                    tomorrow_strategy=item.tomorrow_strategy,
                    risk_notes=item.risk_notes_json,
                    rag_evidence=item.rag_evidence_json,
                    agent_steps=item.agent_trace_json,
                    created_at=item.created_at,
                )
                for item in items
            ]
        )
    )


def create_daily_strategy(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    target_date = parse_date(args.get("date"))
    question = args.get("question")
    if question is not None and not isinstance(question, str):
        raise ValueError("question must be a string")
    return dump_model(create_strategy(db, mcp_user_id(), target_date, question))


TOOL_HANDLERS = {
    "get_daily_meals": get_daily_meals,
    "get_daily_report": get_daily_report,
    "get_strategy_history": get_strategy_history,
    "create_strategy": create_daily_strategy,
}

