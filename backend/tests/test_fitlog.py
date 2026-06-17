from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.schemas.fitlog import StrategyResponse
import app.services.fitlog as fitlog_service


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, email: str = "fitlog@example.com") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "nickname": email.split("@")[0]},
    )
    assert response.status_code == 201
    response = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200


def test_fitlog_goal_meal_report_strategy_and_stub(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate_strategy_text(goal, report, question, evidence):
        return StrategyResponse(
            date=report.date,
            pace_status=report.status,
            summary=f"{report.total_calories} kcal report for {question}",
            today_strategy=f"Use {len(evidence)} evidence items for today's plan.",
            tomorrow_strategy="Keep logging meals tomorrow.",
            risk_notes=["test llm response"],
            rag_evidence=evidence,
        )

    monkeypatch.setattr(fitlog_service, "generate_strategy_text", fake_generate_strategy_text)

    login(client)
    goal = client.post(
        "/api/fitlog/goals",
        json={
            "current_weight_kg": 78.5,
            "target_weight_kg": 70,
            "target_date": "2026-09-30",
            "daily_calorie_target": 1800,
            "activity_level": "moderate",
        },
    )
    assert goal.status_code == 200
    assert client.get("/api/fitlog/goals/me").json()["daily_calorie_target"] == 1800

    foods = '[{"name":"kimchi stew","calories":430,"carbs_g":20,"protein_g":25,"fat_g":24,"portion_text":"1 serving"}]'
    meal = client.post(
        "/api/fitlog/meals",
        data={"meal_date": str(date.today()), "meal_type": "lunch", "memo": "test", "foods_json": foods},
    )
    assert meal.status_code == 201
    assert meal.json()["total_calories"] == 430
    meal_id = meal.json()["id"]

    report = client.get("/api/fitlog/reports/daily", params={"date": str(date.today())})
    assert report.status_code == 200
    assert report.json()["total_calories"] == 430

    strategy = client.post(
        "/api/fitlog/strategy",
        json={"date": str(date.today()), "question": "What should I eat tonight?"},
    )
    assert strategy.status_code == 200
    assert strategy.json()["today_strategy"]
    assert [step["tool"] for step in strategy.json()["agent_steps"]] == [
        "agent_start",
        "get_active_goal",
        "build_daily_report",
        "search_nutrition_knowledge",
        "generate_strategy",
        "save_strategy",
    ]
    strategies = client.get("/api/fitlog/strategy", params={"date": str(date.today())})
    assert strategies.status_code == 200
    assert len(strategies.json()["items"]) == 1
    assert strategies.json()["items"][0]["agent_steps"][-1]["tool"] == "save_strategy"

    image = client.post(
        "/api/fitlog/image-search-test",
        files={"image": ("test.jpg", b"fake", "image/jpeg")},
    )
    assert image.status_code == 200
    assert image.json()["mode"] == "hardcoded_test"

    deleted = client.delete(f"/api/fitlog/meals/{meal_id}")
    assert deleted.status_code == 204

    image_only = client.post(
        "/api/fitlog/meals",
        data={"meal_date": str(date.today()), "meal_type": "dinner", "foods_json": "[]"},
        files={"image": ("ramen.jpg", b"fake", "image/jpeg")},
    )
    assert image_only.status_code == 201
    assert image_only.json()["foods"][0]["name"] == "라면"
    assert image_only.json()["total_calories"] == 500


def test_fitlog_main_meal_upsert_and_snack_time_order(client: TestClient) -> None:
    login(client, "fitlog-order@example.com")
    target_date = str(date.today())
    first_foods = '[{"name":"toast","calories":250,"carbs_g":35,"protein_g":8,"fat_g":8,"portion_text":"1 plate"}]'
    second_foods = '[{"name":"eggs","calories":320,"carbs_g":4,"protein_g":22,"fat_g":22,"portion_text":"2 eggs"}]'

    first = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "breakfast", "meal_time": "08:00", "foods_json": first_foods},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "breakfast", "meal_time": "09:00", "foods_json": second_foods},
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["total_calories"] == 320

    snack_late = '[{"name":"yogurt","calories":120,"carbs_g":15,"protein_g":8,"fat_g":3,"portion_text":"1 cup"}]'
    snack_early = '[{"name":"banana","calories":90,"carbs_g":23,"protein_g":1,"fat_g":0,"portion_text":"1"}]'
    assert client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "15:00", "foods_json": snack_late},
    ).status_code == 201
    assert client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "10:00", "foods_json": snack_early},
    ).status_code == 201

    meals = client.get("/api/fitlog/meals", params={"date": target_date})
    assert meals.status_code == 200
    items = meals.json()["items"]
    assert [item["meal_type"] for item in items].count("breakfast") == 1
    snacks = [item for item in items if item["meal_type"] == "snack"]
    assert [item["meal_time"] for item in snacks] == ["10:00", "15:00"]


def test_fitlog_estimates_nutrition_from_food_name_and_portion(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_llm(name: str, portion_text: str) -> dict:
        return {
            "calories": 90,
            "carbs_g": 23,
            "protein_g": 1,
            "fat_g": 0,
            "source": "llm",
            "raw_response_json": {"unit_calories": 90, "unit_carbs_g": 23, "unit_protein_g": 1, "unit_fat_g": 0},
        }

    monkeypatch.setattr(fitlog_service, "llm_nutrition_estimate", fake_llm)
    login(client, "fitlog-estimate@example.com")
    target_date = str(date.today())
    foods = '[{"name":"banana","portion_text":"1"}]'

    meal = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "16:00", "foods_json": foods},
    )

    assert meal.status_code == 201
    body = meal.json()
    assert body["foods"][0]["name"] == "banana"
    assert body["foods"][0]["portion_text"] == "1"
    assert body["total_calories"] == 90
    assert body["carbs_g"] == 23


def test_fitlog_scales_llm_unit_nutrition_by_portion_count(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_llm(name: str, portion_text: str) -> dict:
        calls.append((name, portion_text))
        return {
            "calories": 500,
            "carbs_g": 78,
            "protein_g": 10,
            "fat_g": 16,
            "source": "llm",
            "raw_response_json": {"unit_calories": 500, "unit_carbs_g": 78, "unit_protein_g": 10, "unit_fat_g": 16},
        }

    monkeypatch.setattr(fitlog_service, "llm_nutrition_estimate", fake_llm)
    login(client, "fitlog-portion@example.com")
    target_date = str(date.today())
    foods = '[{"name":"ramen","portion_text":"12bags"}]'

    meal = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "20:00", "foods_json": foods},
    )

    assert meal.status_code == 201
    body = meal.json()
    assert body["foods"][0]["portion_text"] == "12bags"
    assert body["total_calories"] == 6000
    assert body["carbs_g"] == 936
    assert body["protein_g"] == 120
    assert body["fat_g"] == 192
    assert calls == [("ramen", "1bags")]


def test_fitlog_reuses_unit_nutrition_cache_by_grams(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_llm(name: str, portion_text: str) -> dict:
        calls.append((name, portion_text))
        return {
            "calories": 1,
            "carbs_g": 0.07,
            "protein_g": 0.083333,
            "fat_g": 0.08,
            "source": "llm",
            "raw_response_json": {
                "unit_calories": 430 / 3,
                "unit_carbs_g": 20 / 3,
                "unit_protein_g": 25 / 3,
                "unit_fat_g": 24 / 3,
            },
        }

    monkeypatch.setattr(fitlog_service, "llm_nutrition_estimate", fake_llm)
    login(client, "fitlog-grams@example.com")
    target_date = str(date.today())

    tiny = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "20:00", "foods_json": '[{"name":"kimchi stew","portion_text":"2g"}]'},
    )
    large = client.post(
        "/api/fitlog/meals",
        data={"meal_date": target_date, "meal_type": "snack", "meal_time": "21:00", "foods_json": '[{"name":"kimchi stew","portion_text":"500g"}]'},
    )

    assert tiny.status_code == 201
    assert large.status_code == 201
    assert tiny.json()["total_calories"] == 3
    assert large.json()["total_calories"] == 717
    assert calls == [("kimchi stew", "100g")]
