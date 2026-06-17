import json
import re
import urllib.error
import urllib.request
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.fitlog import FoodNutritionEstimate, GoalProfile, MealFoodItem, MealLog, NutritionKnowledgeDoc, StrategyAdvice
from app.schemas.fitlog import AgentStep, DailyReport, MealFoodItemInput, MealSummary, RagEvidence, StrategyResponse

EMBEDDING_DIM = 1536

DEFAULT_KNOWLEDGE = [
    ("Protein basics", "protein", "감량 중에도 단백질을 충분히 먹으면 포만감과 근육 유지에 도움이 됩니다.", None),
    ("Sodium caution", "sodium", "국물, 찌개, 가공식품은 나트륨이 높을 수 있어 국물 섭취량을 조절하는 편이 좋습니다.", None),
    ("Diet strategy", "diet_strategy", "목표 칼로리를 넘긴 날은 굶기보다 다음 끼니에서 단백질과 채소 중심으로 조절합니다.", None),
    ("Fat balance", "fat", "튀김과 고지방 외식이 많은 날은 다음 식사에서 지방을 낮추고 담백한 단백질원을 선택합니다.", None),
]


def parse_foods(raw: str) -> list[MealFoodItemInput]:
    try:
        data = json.loads(raw)
        return [MealFoodItemInput.model_validate(item) for item in data]
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid foods_json") from exc


def hardcoded_image_foods() -> list[MealFoodItemInput]:
    return [
        MealFoodItemInput(
            name="라면",
            calories=500,
            carbs_g=78,
            protein_g=10,
            fat_g=16,
            portion_text="이미지 테스트 분석",
        )
    ]


def normalize_food_key(value: str | None) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    return normalized or "기본"


def food_has_nutrition(item: MealFoodItemInput) -> bool:
    return item.calories > 0 or item.carbs_g > 0 or item.protein_g > 0 or item.fat_g > 0


def portion_multiplier(portion_text: str, base_grams: float | None = None) -> float:
    normalized = portion_text.replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return 1.0
    value = float(match.group(1))
    if value <= 0:
        return 1.0
    if base_grams and "kg" in normalized:
        return min((value * 1000) / base_grams, 20.0)
    if base_grams and "g" in normalized:
        return min(value / base_grams, 20.0)
    if any(unit in normalized for unit in ["봉지", "개", "인분", "그릇", "팩", "컵", "줄"]):
        return min(value, 20.0)
    return 1.0


def scale_nutrition(calories: int, carbs: float, protein: float, fat: float, multiplier: float) -> tuple[int, float, float, float]:
    return (
        int(round(calories * multiplier)),
        round(carbs * multiplier, 2),
        round(protein * multiplier, 2),
        round(fat * multiplier, 2),
    )


def fallback_nutrition_estimate(name: str, portion_text: str) -> dict:
    text_value = f"{name} {portion_text}".lower()
    if any(keyword in text_value for keyword in ["라면", "ramen"]):
        calories, carbs, protein, fat = 500, 78, 10, 16
        base_grams = 120
    elif any(keyword in text_value for keyword in ["김치찌개", "kimchi stew"]):
        calories, carbs, protein, fat = 430, 20, 25, 24
        base_grams = 300
    elif any(keyword in text_value for keyword in ["바나나", "banana"]):
        calories, carbs, protein, fat = 90, 23, 1, 0
        base_grams = 100
    elif any(keyword in text_value for keyword in ["계란", "egg"]):
        calories, carbs, protein, fat = 80, 1, 7, 5
        base_grams = 50
    else:
        calories, carbs, protein, fat = 350, 45, 18, 10
        base_grams = 250
    multiplier = portion_multiplier(portion_text, base_grams)
    calories, carbs, protein, fat = scale_nutrition(calories, carbs, protein, fat, multiplier)
    return {
        "calories": calories,
        "carbs_g": carbs,
        "protein_g": protein,
        "fat_g": fat,
        "source": "fallback",
        "raw_response_json": {
            "reason": "OPENAI_API_KEY not configured or LLM estimate failed",
            "portion_multiplier": multiplier,
        },
    }


def llm_nutrition_estimate(name: str, portion_text: str) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return fallback_nutrition_estimate(name, portion_text)
    body = json.dumps(
        {
            "model": settings.openai_strategy_agent_model,
            "input": [
                {
                    "role": "system",
                    "content": "Return strict JSON only with keys calories, carbs_g, protein_g, fat_g. Estimate nutrition for the given food and portion. Use one reasonable serving estimate. No medical advice.",
                },
                {"role": "user", "content": json.dumps({"food": name, "portion": portion_text}, ensure_ascii=False)},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(payload.get("output_text") or "{}")
        return {
            "calories": max(0, int(round(float(parsed["calories"])))),
            "carbs_g": max(0.0, float(parsed["carbs_g"])),
            "protein_g": max(0.0, float(parsed["protein_g"])),
            "fat_g": max(0.0, float(parsed["fat_g"])),
            "source": "llm",
            "raw_response_json": parsed,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return fallback_nutrition_estimate(name, portion_text)


def get_or_create_nutrition_estimate(db: Session, item: MealFoodItemInput) -> MealFoodItemInput:
    if food_has_nutrition(item):
        return item
    portion_text = item.portion_text or "1인분"
    normalized_name = normalize_food_key(item.name)
    normalized_portion = normalize_food_key(portion_text)
    cached = db.scalar(
        select(FoodNutritionEstimate).where(
            FoodNutritionEstimate.normalized_name == normalized_name,
            FoodNutritionEstimate.normalized_portion == normalized_portion,
        )
    )
    if cached is None:
        estimated = llm_nutrition_estimate(item.name, portion_text)
        cached = FoodNutritionEstimate(
            name=item.name,
            normalized_name=normalized_name,
            portion_text=portion_text,
            normalized_portion=normalized_portion,
            calories=estimated["calories"],
            carbs_g=estimated["carbs_g"],
            protein_g=estimated["protein_g"],
            fat_g=estimated["fat_g"],
            source=estimated["source"],
            raw_response_json=estimated["raw_response_json"],
        )
        db.add(cached)
        db.flush()
    elif cached.source == "fallback":
        estimated = fallback_nutrition_estimate(item.name, portion_text)
        cached.calories = estimated["calories"]
        cached.carbs_g = estimated["carbs_g"]
        cached.protein_g = estimated["protein_g"]
        cached.fat_g = estimated["fat_g"]
        cached.raw_response_json = estimated["raw_response_json"]
        db.flush()
    return MealFoodItemInput(
        name=item.name,
        portion_text=portion_text,
        calories=cached.calories,
        carbs_g=float(cached.carbs_g),
        protein_g=float(cached.protein_g),
        fat_g=float(cached.fat_g),
    )


def apply_foods(db: Session, meal: MealLog, foods: list[MealFoodItemInput]) -> None:
    if not foods:
        raise HTTPException(status_code=400, detail="At least one food item is required")
    foods = [get_or_create_nutrition_estimate(db, item) for item in foods]
    meal.foods = [
        MealFoodItem(
            name=item.name,
            calories=item.calories,
            carbs_g=item.carbs_g,
            protein_g=item.protein_g,
            fat_g=item.fat_g,
            portion_text=item.portion_text,
        )
        for item in foods
    ]
    meal.total_calories = sum(item.calories for item in foods)
    meal.carbs_g = sum(item.carbs_g for item in foods)
    meal.protein_g = sum(item.protein_g for item in foods)
    meal.fat_g = sum(item.fat_g for item in foods)


def get_active_goal(db: Session, user_id: int) -> GoalProfile | None:
    return db.scalar(select(GoalProfile).where(GoalProfile.user_id == user_id, GoalProfile.is_active.is_(True)))


def get_meal_for_user(db: Session, meal_id: int, user_id: int) -> MealLog:
    meal = db.scalar(
        select(MealLog)
        .where(MealLog.id == meal_id, MealLog.user_id == user_id)
        .options(selectinload(MealLog.foods))
    )
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    return meal


def build_daily_report(db: Session, user_id: int, report_date: date) -> DailyReport:
    goal = get_active_goal(db, user_id)
    meals = db.scalars(
        select(MealLog)
        .where(MealLog.user_id == user_id, MealLog.meal_date == report_date)
        .order_by(MealLog.id.asc())
    ).all()
    total = sum(meal.total_calories for meal in meals)
    carbs = float(sum(float(meal.carbs_g) for meal in meals))
    protein = float(sum(float(meal.protein_g) for meal in meals))
    fat = float(sum(float(meal.fat_g) for meal in meals))
    target = goal.daily_calorie_target if goal else None
    remaining = target - total if target is not None else None
    warnings: list[str] = []
    if goal is None:
        warnings.append("목표가 아직 설정되지 않았습니다.")
    if not meals:
        warnings.append("선택한 날짜에 식단 기록이 없습니다.")
    if remaining is not None and remaining < 0:
        warnings.append("오늘 목표 칼로리를 초과했습니다.")
    if total > 0 and protein * 4 < total * 0.15:
        warnings.append("단백질 비율이 낮아 보입니다.")
    status = (
        "insufficient_data"
        if not meals or goal is None
        else "over"
        if remaining is not None and remaining < -200
        else "slightly_over"
        if remaining is not None and remaining < 0
        else "on_track"
    )
    return DailyReport(
        date=report_date,
        daily_calorie_target=target,
        total_calories=total,
        remaining_calories=remaining,
        carbs_g=carbs,
        protein_g=protein,
        fat_g=fat,
        meal_count=len(meals),
        status=status,
        warnings=warnings,
        meals=[
            MealSummary(
                id=meal.id,
                meal_type=meal.meal_type,
                total_calories=meal.total_calories,
                carbs_g=float(meal.carbs_g),
                protein_g=float(meal.protein_g),
                fat_g=float(meal.fat_g),
            )
            for meal in meals
        ],
    )


def is_postgresql(db: Session) -> bool:
    return bool(db.bind and db.bind.dialect.name == "postgresql")


def tokenize(text_value: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", text_value.lower())


def langchain_text_embedding(text_value: str) -> list[float] | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            dimensions=settings.openai_embedding_dimensions,
        )
        vector = embeddings.embed_query(text_value)
    except Exception:
        return None
    if len(vector) != settings.openai_embedding_dimensions:
        return None
    return [round(float(value), 6) for value in vector]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def extract_openai_response_text(payload: dict) -> str:
    text_value = payload.get("output_text")
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            content_text = content.get("text")
            if isinstance(content_text, str):
                chunks.append(content_text)
    return "\n".join(chunks).strip()


def parse_json_text(text_value: str) -> dict:
    cleaned = text_value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def normalize_strategy_payload(parsed: dict) -> dict:
    risk_notes = parsed.get("risk_notes")
    if isinstance(risk_notes, str):
        parsed["risk_notes"] = [risk_notes]
    elif risk_notes is None:
        parsed["risk_notes"] = []
    elif not isinstance(risk_notes, list):
        parsed["risk_notes"] = [str(risk_notes)]
    else:
        parsed["risk_notes"] = [str(note) for note in risk_notes]
    return parsed


def ensure_knowledge(db: Session) -> None:
    exists = db.scalar(select(NutritionKnowledgeDoc.id).limit(1))
    if exists is None:
        for title, category, content, source in DEFAULT_KNOWLEDGE:
            db.add(NutritionKnowledgeDoc(title=title, category=category, content=content, source_url=source))
        db.commit()
    ensure_knowledge_embeddings(db)


def ensure_knowledge_embeddings(db: Session) -> None:
    if not is_postgresql(db):
        return
    rows = db.execute(
        text(
            """
            SELECT id, title, category, content
            FROM nutrition_knowledge_docs
            WHERE embedding IS NULL
            """
        )
    ).mappings().all()
    for row in rows:
        embedding_values = langchain_text_embedding(f"{row['title']} {row['category']} {row['content']}")
        if embedding_values is None:
            continue
        embedding = vector_literal(embedding_values)
        db.execute(
            text("UPDATE nutrition_knowledge_docs SET embedding = CAST(:embedding AS vector) WHERE id = :id"),
            {"embedding": embedding, "id": row["id"]},
        )
    if rows:
        db.commit()


def keyword_search_knowledge(db: Session, query: str, limit: int) -> list[RagEvidence]:
    words = set(tokenize(query))
    docs = db.scalars(select(NutritionKnowledgeDoc)).all()
    scored = []
    for doc in docs:
        haystack = f"{doc.title} {doc.category} {doc.content}".lower()
        score = sum(1 for word in words if word in haystack)
        scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        RagEvidence(title=doc.title, snippet=doc.content[:180], source_url=doc.source_url)
        for score, doc in scored[:limit]
        if score > 0 or not words
    ] or [
        RagEvidence(title=doc.title, snippet=doc.content[:180], source_url=doc.source_url)
        for _, doc in scored[:limit]
    ]


def search_knowledge(db: Session, query: str, limit: int = 3) -> list[RagEvidence]:
    ensure_knowledge(db)
    if is_postgresql(db):
        try:
            query_embedding = langchain_text_embedding(query)
            if query_embedding is None:
                return keyword_search_knowledge(db, query, limit)
            rows = db.execute(
                text(
                    """
                    SELECT title, content, source_url
                    FROM nutrition_knowledge_docs
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {"embedding": vector_literal(query_embedding), "limit": limit},
            ).mappings().all()
            if rows:
                return [
                    RagEvidence(title=row["title"], snippet=row["content"][:180], source_url=row["source_url"])
                    for row in rows
                ]
        except Exception:
            db.rollback()
    return keyword_search_knowledge(db, query, limit)


def _generate_strategy_text_legacy(goal: GoalProfile, report: DailyReport, question: str | None, evidence: list[RagEvidence]) -> StrategyResponse:
    settings = get_settings()
    prompt = {
        "goal": {
            "current_weight_kg": float(goal.current_weight_kg),
            "target_weight_kg": float(goal.target_weight_kg),
            "target_date": goal.target_date.isoformat(),
            "daily_calorie_target": goal.daily_calorie_target,
        },
        "report": report.model_dump(mode="json"),
        "question": question or "오늘 목표 달성을 위해 무엇을 조정해야 하나요?",
        "evidence": [item.model_dump() for item in evidence],
    }
    fallback = StrategyResponse(
        date=report.date,
        pace_status=report.status if report.status in {"on_track", "slightly_over", "over", "insufficient_data"} else "on_track",
        summary="오늘 기록을 기준으로 목표 대비 식사 전략을 조정했습니다.",
        today_strategy="남은 식사는 목표 칼로리 안에서 단백질과 채소를 우선하고, 고지방 간식은 줄이는 방향이 좋습니다.",
        tomorrow_strategy="내일은 첫 식사부터 단백질을 확보하고, 오늘 초과한 항목이 있다면 같은 종류의 외식을 줄이세요.",
        risk_notes=["영양 정보는 입력값 기준입니다.", "의학적 진단이나 치료 조언은 아닙니다."],
        rag_evidence=evidence,
    )
    if not settings.openai_api_key:
        return fallback

    body = json.dumps(
        {
            "model": settings.openai_strategy_agent_model,
            "input": [
                {
                    "role": "system",
                    "content": "Return strict JSON with keys pace_status, summary, today_strategy, tomorrow_strategy, risk_notes. Do not give medical diagnosis.",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text_value = payload.get("output_text") or ""
        parsed = json.loads(text_value)
        return StrategyResponse(date=report.date, rag_evidence=evidence, **parsed)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return fallback


def fallback_strategy_response(report: DailyReport, question: str | None, evidence: list[RagEvidence], reason: str) -> StrategyResponse:
    question_text = (question or "오늘 목표 달성을 위해 무엇을 조정해야 하나요?").strip()
    remaining = report.remaining_calories
    evidence_title = evidence[0].title if evidence else "기본 영양 지식"

    if report.meal_count == 0:
        summary = f"{report.date.isoformat()}에는 식단 기록이 없어 정확한 전략을 만들기 어렵습니다."
        today_strategy = "먼저 아침, 점심, 저녁 중 실제로 먹은 식사를 1개 이상 기록하세요. 이후 남은 칼로리와 단백질 비율을 기준으로 조정할 수 있습니다."
        tomorrow_strategy = "내일은 식사 직후 바로 기록하는 흐름을 우선 만들고, 각 식사에 단백질 식품을 하나씩 포함하세요."
    elif remaining is not None and remaining < 0:
        summary = f"{report.total_calories} kcal로 목표보다 {abs(remaining)} kcal 초과했습니다."
        today_strategy = "오늘 남은 식사는 추가 칼로리를 줄이고, 물과 저열량 채소 중심으로 마무리하세요. 야식이나 음료 칼로리는 피하는 편이 좋습니다."
        tomorrow_strategy = "내일은 첫 식사부터 단백질을 먼저 정하고, 나트륨이 높은 국물/가공식품은 분량을 줄여 초과를 방지하세요."
    elif remaining is not None:
        summary = f"{report.total_calories} kcal를 기록했고 목표까지 {remaining} kcal 남았습니다."
        today_strategy = "남은 칼로리 안에서 단백질이 있는 식사를 우선 선택하세요. 탄수화물은 운동량이나 허기에 맞춰 분량을 조절하세요."
        tomorrow_strategy = "내일도 같은 시간대에 식사를 기록하고, 부족했던 영양소가 있으면 첫 식사에서 보완하세요."
    else:
        summary = f"{report.total_calories} kcal를 기록했지만 활성 목표가 없어 목표 대비 판단은 제한됩니다."
        today_strategy = "먼저 목표 칼로리를 설정하면 더 구체적인 조정 전략을 만들 수 있습니다."
        tomorrow_strategy = "목표 체중, 목표 날짜, 하루 목표 칼로리를 설정한 뒤 식단을 기록하세요."

    if report.total_calories > 0 and report.protein_g * 4 < report.total_calories * 0.15:
        today_strategy += " 현재 단백질 비율이 낮아 보이므로 다음 식사에는 계란, 닭가슴살, 두부, 생선 같은 단백질을 추가하세요."

    return StrategyResponse(
        date=report.date,
        pace_status=report.status if report.status in {"on_track", "slightly_over", "over", "insufficient_data"} else "on_track",
        summary=f"{summary} 질문: {question_text}",
        today_strategy=today_strategy,
        tomorrow_strategy=tomorrow_strategy,
        risk_notes=[
            reason,
            f"참고 근거: {evidence_title}",
            "의학적 진단이나 치료 조언이 아니라 식단 기록 기반의 일반적인 조정 제안입니다.",
        ],
        rag_evidence=evidence,
    )


def generate_strategy_text(goal: GoalProfile, report: DailyReport, question: str | None, evidence: list[RagEvidence]) -> StrategyResponse:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for FitLog Diet Strategy Agent")

    prompt = {
        "goal": {
            "current_weight_kg": float(goal.current_weight_kg),
            "target_weight_kg": float(goal.target_weight_kg),
            "target_date": goal.target_date.isoformat(),
            "daily_calorie_target": goal.daily_calorie_target,
        },
        "report": report.model_dump(mode="json"),
        "question": question or "오늘 목표 달성을 위해 무엇을 조정해야 하나요?",
        "evidence": [item.model_dump() for item in evidence],
    }
    body = json.dumps(
        {
            "model": settings.openai_strategy_agent_model,
            "input": [
                {
                    "role": "system",
                    "content": "Return strict JSON with keys pace_status, summary, today_strategy, tomorrow_strategy, risk_notes. Do not give medical diagnosis. Reflect the user's question and daily report.",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        parsed = normalize_strategy_payload(parse_json_text(extract_openai_response_text(payload)))
        return StrategyResponse(date=report.date, rag_evidence=evidence, **parsed)
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(status_code=502, detail=f"OpenAI API error {exc.code}: {error_text}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI API connection failed: {exc}") from exc
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI response parsing failed: {exc}") from exc


def _create_strategy_pipeline_without_agent(db: Session, user_id: int, target_date: date, question: str | None) -> StrategyResponse:
    goal = get_active_goal(db, user_id)
    if goal is None:
        return StrategyResponse(
            date=target_date,
            pace_status="insufficient_data",
            summary="목표 설정이 필요합니다.",
            today_strategy="먼저 현재 체중, 목표 체중, 목표 날짜, 하루 목표 칼로리를 설정하세요.",
            tomorrow_strategy="목표가 설정되면 식단 기록을 바탕으로 조정 전략을 만들 수 있습니다.",
            risk_notes=["의학적 진단이나 치료 조언은 아닙니다."],
            rag_evidence=[],
        )
    report = build_daily_report(db, user_id, target_date)
    evidence = search_knowledge(db, " ".join([question or "", *report.warnings, report.status]))
    response = generate_strategy_text(goal, report, question, evidence)
    db.add(
        StrategyAdvice(
            user_id=user_id,
            goal_profile_id=goal.id,
            target_date=target_date,
            question=question,
            pace_status=response.pace_status,
            summary=response.summary,
            today_strategy=response.today_strategy,
            tomorrow_strategy=response.tomorrow_strategy,
            risk_notes_json=response.risk_notes,
            rag_evidence_json=[item.model_dump() for item in response.rag_evidence],
        )
    )
    db.commit()
    return response


class FitLogDietStrategyAgent:
    """Tool-orchestrating agent for daily FitLog diet strategy."""

    def __init__(self, db: Session, user_id: int, target_date: date, question: str | None):
        self.db = db
        self.user_id = user_id
        self.target_date = target_date
        self.question = question
        self.steps: list[AgentStep] = []

    def record(self, tool: str, status: str, summary: str) -> None:
        self.steps.append(AgentStep(tool=tool, status=status, summary=summary))

    def load_goal(self) -> GoalProfile | None:
        goal = get_active_goal(self.db, self.user_id)
        self.record(
            "get_active_goal",
            "ok" if goal else "missing",
            "Loaded active goal profile." if goal else "Active goal profile is required before strategy generation.",
        )
        return goal

    def load_daily_report(self) -> DailyReport:
        report = build_daily_report(self.db, self.user_id, self.target_date)
        self.record(
            "build_daily_report",
            "ok",
            f"Loaded {report.meal_count} meals and {report.total_calories} kcal for {report.date.isoformat()}.",
        )
        return report

    def retrieve_evidence(self, report: DailyReport) -> list[RagEvidence]:
        query = " ".join([self.question or "", *report.warnings, report.status])
        evidence = search_knowledge(self.db, query)
        self.record("search_nutrition_knowledge", "ok", f"Retrieved {len(evidence)} RAG evidence items.")
        return evidence

    def generate_strategy(self, goal: GoalProfile, report: DailyReport, evidence: list[RagEvidence]) -> StrategyResponse:
        response = generate_strategy_text(goal, report, self.question, evidence)
        self.record("generate_strategy", "ok", f"Generated strategy with pace status {response.pace_status}.")
        response.agent_steps = self.steps.copy()
        return response

    def save_strategy(self, goal: GoalProfile, response: StrategyResponse) -> StrategyResponse:
        self.record("save_strategy", "ok", "Saved generated strategy and agent trace.")
        response.agent_steps = self.steps.copy()
        self.db.add(
            StrategyAdvice(
                user_id=self.user_id,
                goal_profile_id=goal.id,
                target_date=self.target_date,
                question=self.question,
                pace_status=response.pace_status,
                summary=response.summary,
                today_strategy=response.today_strategy,
                tomorrow_strategy=response.tomorrow_strategy,
                risk_notes_json=response.risk_notes,
                rag_evidence_json=[item.model_dump() for item in response.rag_evidence],
                agent_trace_json=[item.model_dump() for item in self.steps],
            )
        )
        self.db.commit()
        return response

    def missing_goal_response(self) -> StrategyResponse:
        return StrategyResponse(
            date=self.target_date,
            pace_status="insufficient_data",
            summary="Active goal profile is required before strategy generation.",
            today_strategy="Set your current weight, target weight, target date, and daily calorie target first.",
            tomorrow_strategy="After the goal is configured, the agent can use meal records and RAG evidence to create a strategy.",
            risk_notes=["This is not medical diagnosis or treatment advice."],
            rag_evidence=[],
            agent_steps=self.steps.copy(),
        )

    def run(self) -> StrategyResponse:
        self.record("agent_start", "ok", "FitLog Diet Strategy Agent started.")
        goal = self.load_goal()
        if goal is None:
            return self.missing_goal_response()
        report = self.load_daily_report()
        evidence = self.retrieve_evidence(report)
        response = self.generate_strategy(goal, report, evidence)
        return self.save_strategy(goal, response)


def create_strategy(db: Session, user_id: int, target_date: date, question: str | None) -> StrategyResponse:
    return FitLogDietStrategyAgent(db, user_id, target_date, question).run()
