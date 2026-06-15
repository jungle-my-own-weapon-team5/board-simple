# FitLog Agent Implementation Plan

## Milestone 0: Project Guardrails and Configuration

Priority: P0

Deliverables:
- Add OpenAI and upload directory settings to backend configuration.
- Add matching values to `.env.example`.
- Keep model names configurable through environment variables.
- Add a FitLog navigation entry without removing the existing board.

Implementation details:
- Backend settings:
  - `openai_api_key`
  - `openai_strategy_agent_model`
  - `openai_fallback_model`
  - `upload_dir`
- Frontend navigation:
  - Brand can remain, but primary route should expose `/fitlog`.
  - Logged-in users should see FitLog actions.

Acceptance criteria:
- App starts with default settings when optional AI values are absent except API key-dependent strategy calls.
- Frontend build still passes after route additions.

## Milestone 1: Goal Profile

Priority: P0

Deliverables:
- `goal_profiles` SQLAlchemy model.
- Alembic migration.
- Pydantic schemas.
- Goal API.
- Goal setup/edit screen.

Implementation details:
- User can have one active goal.
- `POST /api/fitlog/goals` should upsert the active goal.
- `GET /api/fitlog/goals/me` returns 404 when not configured.
- Validate:
  - weights are positive
  - target date is present
  - daily calorie target is positive
  - activity level is one of `low`, `moderate`, `high`

Acceptance criteria:
- Logged-in user can create and retrieve a goal.
- User cannot read or update another user's goal.
- FitLog dashboard shows an empty state if goal is missing.

## Milestone 2: Meal Logs and Food Items

Priority: P0

Deliverables:
- `meal_logs` and `meal_food_items` SQLAlchemy models.
- Alembic migration.
- Meal CRUD API.
- Manual meal entry and edit screens.

Implementation details:
- `POST /api/fitlog/meals` uses `multipart/form-data`.
- Required fields:
  - `meal_date`
  - `meal_type`
  - `foods_json`
- Optional fields:
  - `memo`
  - `image`
  - `crop_image`
  - `crop_x`, `crop_y`, `crop_width`, `crop_height`
- `foods_json` is parsed into food item rows.
- Meal aggregate values are calculated from food items server-side.
- Updating a meal replaces the food items and recalculates aggregates.

Acceptance criteria:
- User can create, list, view, update, and delete meals.
- Meal totals equal food item totals.
- Other users cannot access a meal.

## Milestone 3: Image Upload and Canvas Crop

Priority: P1

Deliverables:
- Upload utility in backend.
- Static or authenticated serving path for uploaded images.
- Frontend image preview.
- Canvas single-rectangle crop.
- Meal detail display for original and crop images.

Implementation details:
- Store images under `UPLOAD_DIR/meals/{user_id}/`.
- Use generated filenames, not user-provided filenames.
- Accept common image MIME types only.
- Frontend crop behavior:
  - user selects one rectangle
  - Canvas creates a crop blob
  - crop coordinates are sent in original-image coordinate space
- Meal save sends both original and crop when available.

Acceptance criteria:
- Meal can be saved without image.
- Meal can be saved with original image only.
- Meal can be saved with original and crop image.
- Detail screen renders stored image paths.

## Milestone 4: Daily Nutrition Report

Priority: P0

Deliverables:
- Daily report service.
- `GET /api/fitlog/reports/daily`.
- Report screen.
- Dashboard summary card.

Implementation details:
- Calculate report on request from `meal_logs`.
- Include:
  - total calories
  - remaining calories if goal exists
  - carbs, protein, fat totals
  - meal count
  - warnings
  - meal summaries
- Basic warnings:
  - no goal
  - no meals
  - calories over target
  - protein appears low relative to total intake

Acceptance criteria:
- Report updates after meal create/update/delete.
- Report works with no goal and no meals using clear empty states.

## Milestone 5: Nutrition Knowledge Text RAG

Priority: P1

Deliverables:
- `nutrition_knowledge_docs` model.
- Alembic migration.
- Seed data for initial nutrition guidance.
- Keyword scoring search service.

Implementation details:
- Seed categories:
  - protein
  - sodium
  - fat
  - diet_strategy
  - food_reference
- Search input should include:
  - user's question
  - report warning keywords
  - goal status keywords
- Return top 3 evidence snippets.

Acceptance criteria:
- Strategy service can retrieve relevant nutrition snippets without vector DB.
- Missing seed docs does not crash strategy generation.

## Milestone 6: Strategy Agent

Priority: P0

Deliverables:
- OpenAI strategy client.
- Strategy service.
- `strategy_advices` model.
- Alembic migration.
- `POST /api/fitlog/strategy`.
- Coach screen.

Implementation details:
- Strategy prompt input:
  - active goal
  - daily report
  - user question
  - RAG evidence snippets
  - safety policy
- Output should be parsed into:
  - `pace_status`
  - `summary`
  - `today_strategy`
  - `tomorrow_strategy`
  - `risk_notes`
  - `rag_evidence`
- If OpenAI API key is missing, return a controlled service error.
- Store successful responses in `strategy_advices`.

Acceptance criteria:
- Strategy requires login.
- Strategy handles no goal and no meals with useful guidance.
- Successful strategy response is stored and shown in UI.

## Milestone 7: Image Search Test Stub

Priority: P2

Deliverables:
- `POST /api/fitlog/image-search-test`.
- `/fitlog/image-search-test` screen.
- Optional image preview and crop reuse from meal form logic.

Implementation details:
- Accept any image upload.
- Do not run ResNet, pgvector, or OpenAI.
- Return hardcoded top-k candidates:
  - 김치찌개
  - 된장찌개
  - 비빔밥
- Response must include `mode: "hardcoded_test"`.
- Test result must not create a meal automatically.

Acceptance criteria:
- Any uploaded image returns the hardcoded candidates.
- Test screen clearly separates this from real meal logging.

## Milestone 8: Verification and Cleanup

Priority: P0

Deliverables:
- Backend tests.
- Frontend build verification.
- README or docs note for running FitLog.

Test requirements:
- Goal CRUD and ownership.
- Meal CRUD and ownership.
- Food item aggregate calculation.
- Upload path persistence.
- Daily report calculation.
- Strategy empty states.
- Strategy persistence with mocked OpenAI client.
- Image search test stub response.

Commands:
- Backend: `pytest`
- Frontend: `npm run build`

Definition of done:
- New FitLog flow works from login to goal, meal, report, and strategy.
- Image search exists only as a hardcoded test stub.
- Existing board functionality is not intentionally removed.

