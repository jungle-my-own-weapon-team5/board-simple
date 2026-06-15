from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.fitlog import GoalProfile, MealLog
from app.models.fitlog import StrategyAdvice
from app.models.user import User
from app.schemas.fitlog import (
    DailyReport,
    GoalProfileCreate,
    GoalProfileRead,
    ImageSearchTestResponse,
    MealLogList,
    MealLogRead,
    StrategyRequest,
    StrategyResponse,
    StrategyAdviceList,
    StrategyAdviceRead,
)
from app.services.fitlog import apply_foods, build_daily_report, create_strategy, get_active_goal, get_meal_for_user, hardcoded_image_foods, parse_foods
from app.services.uploads import save_upload

router = APIRouter(prefix="/fitlog", tags=["fitlog"])
MAIN_MEAL_TYPES = {"breakfast", "lunch", "dinner"}
MEAL_TYPES = MAIN_MEAL_TYPES | {"snack"}


def _meal_sort_key(meal: MealLog) -> tuple[int, str, int]:
    order = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}
    return (order.get(meal.meal_type, 99), meal.meal_time or "99:99", meal.id)


@router.post("/goals", response_model=GoalProfileRead)
def upsert_goal(
    payload: GoalProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalProfile:
    goal = get_active_goal(db, current_user.id)
    if goal is None:
        goal = GoalProfile(user_id=current_user.id, is_active=True, **payload.model_dump())
        db.add(goal)
    else:
        for key, value in payload.model_dump().items():
            setattr(goal, key, value)
    db.commit()
    db.refresh(goal)
    return goal


@router.get("/goals/me", response_model=GoalProfileRead)
def read_goal(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalProfile:
    goal = get_active_goal(db, current_user.id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not configured")
    return goal


@router.post("/meals", response_model=MealLogRead, status_code=status.HTTP_201_CREATED)
def create_meal(
    meal_date: date = Form(...),
    meal_type: str = Form(...),
    meal_time: str | None = Form(default=None),
    foods_json: str = Form(default="[]"),
    memo: str | None = Form(default=None),
    crop_x: int | None = Form(default=None),
    crop_y: int | None = Form(default=None),
    crop_width: int | None = Form(default=None),
    crop_height: int | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    crop_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealLog:
    if meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid meal_type")
    meal = None
    if meal_type in MAIN_MEAL_TYPES:
        meal = db.scalar(
            select(MealLog)
            .where(
                MealLog.user_id == current_user.id,
                MealLog.meal_date == meal_date,
                MealLog.meal_type == meal_type,
            )
            .options(selectinload(MealLog.foods))
        )
    if meal is None:
        meal = MealLog(user_id=current_user.id)
        db.add(meal)
    meal.meal_date = meal_date
    meal.meal_type = meal_type
    meal.meal_time = meal_time
    meal.memo = memo
    meal.image_path = save_upload(image, current_user.id, "original")
    meal.crop_image_path = save_upload(crop_image, current_user.id, "crop")
    meal.crop_x = crop_x
    meal.crop_y = crop_y
    meal.crop_width = crop_width
    meal.crop_height = crop_height
    foods = parse_foods(foods_json)
    if not foods and (image is not None or crop_image is not None):
        foods = hardcoded_image_foods()
    apply_foods(db, meal, foods)
    db.commit()
    return get_meal_for_user(db, meal.id, current_user.id)


@router.get("/meals", response_model=MealLogList)
def list_meals(
    date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealLogList:
    meals = db.scalars(
        select(MealLog)
        .where(MealLog.user_id == current_user.id, MealLog.meal_date == date)
        .options(selectinload(MealLog.foods))
        .order_by(MealLog.id.asc())
    ).all()
    return MealLogList(items=sorted(meals, key=_meal_sort_key))


@router.get("/meals/{meal_id}", response_model=MealLogRead)
def read_meal(meal_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MealLog:
    return get_meal_for_user(db, meal_id, current_user.id)


@router.put("/meals/{meal_id}", response_model=MealLogRead)
def update_meal(
    meal_id: int,
    meal_date: date = Form(...),
    meal_type: str = Form(...),
    meal_time: str | None = Form(default=None),
    foods_json: str = Form(default="[]"),
    memo: str | None = Form(default=None),
    crop_x: int | None = Form(default=None),
    crop_y: int | None = Form(default=None),
    crop_width: int | None = Form(default=None),
    crop_height: int | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    crop_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealLog:
    meal = get_meal_for_user(db, meal_id, current_user.id)
    if meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid meal_type")
    meal.meal_date = meal_date
    meal.meal_type = meal_type
    meal.meal_time = meal_time
    meal.memo = memo
    meal.crop_x = crop_x
    meal.crop_y = crop_y
    meal.crop_width = crop_width
    meal.crop_height = crop_height
    new_image = save_upload(image, current_user.id, "original")
    new_crop = save_upload(crop_image, current_user.id, "crop")
    meal.image_path = new_image or meal.image_path
    meal.crop_image_path = new_crop or meal.crop_image_path
    foods = parse_foods(foods_json)
    if not foods and (image is not None or crop_image is not None or meal.image_path or meal.crop_image_path):
        foods = hardcoded_image_foods()
    apply_foods(db, meal, foods)
    db.commit()
    return get_meal_for_user(db, meal.id, current_user.id)


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal(meal_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    meal = get_meal_for_user(db, meal_id, current_user.id)
    db.delete(meal)
    db.commit()


@router.get("/reports/daily", response_model=DailyReport)
def daily_report(date: date, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> DailyReport:
    return build_daily_report(db, current_user.id, date)


@router.post("/strategy", response_model=StrategyResponse)
def strategy(
    payload: StrategyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StrategyResponse:
    return create_strategy(db, current_user.id, payload.date, payload.question)


@router.get("/strategy", response_model=StrategyAdviceList)
def list_strategy(
    date: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StrategyAdviceList:
    statement = select(StrategyAdvice).where(StrategyAdvice.user_id == current_user.id)
    if date is not None:
        statement = statement.where(StrategyAdvice.target_date == date)
    items = db.scalars(statement.order_by(StrategyAdvice.created_at.desc())).all()
    return StrategyAdviceList(
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
                created_at=item.created_at,
            )
            for item in items
        ]
    )


@router.post("/image-search-test", response_model=ImageSearchTestResponse)
def image_search_test(image: UploadFile = File(...), current_user: User = Depends(get_current_user)) -> ImageSearchTestResponse:
    return ImageSearchTestResponse(
        query_handled=True,
        mode="hardcoded_test",
        top_k=[
            {"food_name": "김치찌개", "similarity": 0.92, "estimated_calories": 430, "carbs_g": 20, "protein_g": 25, "fat_g": 24, "notes": ["테스트용 하드코딩 결과입니다."]},
            {"food_name": "된장찌개", "similarity": 0.87, "estimated_calories": 360, "carbs_g": 18, "protein_g": 22, "fat_g": 18, "notes": ["테스트용 후보입니다."]},
            {"food_name": "비빔밥", "similarity": 0.81, "estimated_calories": 620, "carbs_g": 88, "protein_g": 22, "fat_g": 18, "notes": ["테스트용 후보입니다."]},
        ],
    )
