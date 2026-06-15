# FitLog Agent Spec

## 1. Project Goal

FitLog Agent is a diet coaching service that helps a user adjust strategy toward a weight-loss goal. The first implementation focuses on goal setup, manual meal logging, daily nutrition reports, text RAG, and an AI strategy agent. Image upload and crop storage are included, but image-based RAG search is only a hardcoded test feature.

## 2. Core User Flow

1. User signs up or logs in.
2. User creates an active weight-loss goal.
3. User records a meal with manual food and nutrition values.
4. User may attach an original meal image and crop a single food region with Canvas.
5. The system stores image file paths, crop coordinates, food items, and meal totals.
6. The system calculates a daily nutrition report.
7. The strategy agent compares the report against the user's goal.
8. The agent returns today's remaining meal strategy and tomorrow's adjustment strategy.

## 3. In Scope

- FitLog domain separate from the existing board domain.
- Goal profile CRUD for the current user.
- Manual meal log CRUD.
- Meal food item CRUD through meal create/update.
- Original image upload and file path persistence.
- Canvas-based single crop image generation on the frontend.
- Crop image upload and file path persistence.
- Daily nutrition report calculation.
- Text RAG over nutrition knowledge documents.
- OpenAI-based strategy generation with configurable model names.
- Hardcoded image search test endpoint and screen.

## 4. Out of Scope

- Real food image recognition.
- ResNet-18 inference.
- Projection layer training.
- pgvector image embedding search.
- Automatic nutrition estimation from image.
- Using image search results to create meal logs automatically.
- Medical diagnosis, treatment, or extreme weight-loss prescription.

## 5. Tech Stack

- Frontend: Next.js App Router, TypeScript, Tailwind CSS, shadcn-style UI components, Zustand, Canvas API.
- Backend: FastAPI, SQLAlchemy ORM, Pydantic, Alembic.
- Database: PostgreSQL.
- AI: OpenAI Responses API for strategy generation.
- RAG: keyword-based text retrieval for nutrition knowledge.
- Storage: local upload directory for images; DB stores paths and metadata.

## 6. Environment Variables

```env
OPENAI_API_KEY=
OPENAI_STRATEGY_AGENT_MODEL=gpt-5.4-mini
OPENAI_FALLBACK_MODEL=gpt-5.5
UPLOAD_DIR=uploads
```

Model names must be loaded from configuration, not hardcoded in agent services.

## 7. Database Design

### goal_profiles

Stores one active weight-loss goal per user.

| Column | Type | Notes |
|---|---|---|
| id | integer PK | Goal id |
| user_id | FK users.id | Owner |
| current_weight_kg | numeric | Current weight |
| target_weight_kg | numeric | Target weight |
| target_date | date | Goal deadline |
| daily_calorie_target | integer | Daily kcal target |
| activity_level | string | low, moderate, high |
| is_active | boolean | Active goal flag |
| created_at | datetime | Created timestamp |
| updated_at | datetime | Updated timestamp |

### meal_logs

Stores one meal record and aggregate nutrition values.

| Column | Type | Notes |
|---|---|---|
| id | integer PK | Meal id |
| user_id | FK users.id | Owner |
| meal_date | date | Meal date |
| meal_type | string | breakfast, lunch, dinner, snack |
| memo | text nullable | User note |
| image_path | string nullable | Original image path |
| crop_image_path | string nullable | Cropped image path |
| crop_x | integer nullable | Original-image crop x |
| crop_y | integer nullable | Original-image crop y |
| crop_width | integer nullable | Crop width |
| crop_height | integer nullable | Crop height |
| total_calories | integer | Aggregate kcal |
| carbs_g | numeric | Aggregate carbs |
| protein_g | numeric | Aggregate protein |
| fat_g | numeric | Aggregate fat |
| created_at | datetime | Created timestamp |
| updated_at | datetime | Updated timestamp |

### meal_food_items

Stores food-level manual nutrition entries for a meal.

| Column | Type | Notes |
|---|---|---|
| id | integer PK | Food item id |
| meal_log_id | FK meal_logs.id | Parent meal |
| name | string | Food name |
| calories | integer | kcal |
| carbs_g | numeric | Carbs |
| protein_g | numeric | Protein |
| fat_g | numeric | Fat |
| portion_text | string nullable | Portion label |
| created_at | datetime | Created timestamp |
| updated_at | datetime | Updated timestamp |

### nutrition_knowledge_docs

Stores text RAG documents for strategy generation.

| Column | Type | Notes |
|---|---|---|
| id | integer PK | Document id |
| title | string | Title |
| category | string | protein, sodium, fat, diet_strategy, food_reference |
| content | text | Searchable body |
| source_url | string nullable | Source |
| created_at | datetime | Created timestamp |
| updated_at | datetime | Updated timestamp |

### strategy_advices

Stores generated agent strategy responses.

| Column | Type | Notes |
|---|---|---|
| id | integer PK | Advice id |
| user_id | FK users.id | Owner |
| goal_profile_id | FK goal_profiles.id | Goal used |
| target_date | date | Advice date |
| question | text nullable | User question |
| pace_status | string | on_track, slightly_over, over, insufficient_data, goal_too_aggressive |
| summary | text | Short summary |
| today_strategy | text | Today's strategy |
| tomorrow_strategy | text | Tomorrow adjustment |
| risk_notes_json | json | Safety notes |
| rag_evidence_json | json | Retrieved evidence |
| created_at | datetime | Created timestamp |

## 8. API Specification

### Goal API

- `POST /api/fitlog/goals`: create or update the current user's active goal.
- `GET /api/fitlog/goals/me`: get current user's active goal.

### Meal API

- `POST /api/fitlog/meals`: create a manual meal log with optional original image, optional crop image, crop coordinates, and `foods_json`.
- `GET /api/fitlog/meals?date=YYYY-MM-DD`: list current user's meals for a date.
- `GET /api/fitlog/meals/{meal_id}`: get one meal with food items.
- `PUT /api/fitlog/meals/{meal_id}`: replace meal metadata, images, crop coordinates, and food items.
- `DELETE /api/fitlog/meals/{meal_id}`: delete a meal.

### Report API

- `GET /api/fitlog/reports/daily?date=YYYY-MM-DD`: calculate daily calories, macros, remaining calories, warnings, and meal summaries.

### Strategy API

- `POST /api/fitlog/strategy`: generate and store strategy advice from goal, daily report, user question, and text RAG evidence.

### Image Search Test API

- `POST /api/fitlog/image-search-test`: accept any uploaded image and return hardcoded top-k food candidates.

## 9. Frontend Screens

- `/fitlog`: dashboard with goal progress, today's summary, and latest advice.
- `/fitlog/goal`: goal setup and edit form.
- `/fitlog/meals/new`: manual meal entry, optional image upload, optional Canvas crop.
- `/fitlog/meals/{mealId}`: meal detail and edit screen.
- `/fitlog/report?date=YYYY-MM-DD`: daily nutrition report.
- `/fitlog/coach`: strategy question and answer screen.
- `/fitlog/image-search-test`: image upload/crop test screen returning hardcoded candidates.

## 10. Agent Rules

- Always compare current records against the active goal.
- If no goal exists, ask the user to set a goal.
- If no meal records exist for the selected date, ask the user to enter meals.
- Use user-entered nutrition values as calculation source.
- Include today's remaining strategy and tomorrow's adjustment.
- Include non-medical safety notes.
- Never diagnose disease, prescribe treatment, or recommend extreme weight loss.

## 11. Image Handling Rules

- The original image is optional for meal creation.
- Crop image is optional and generated on the frontend by Canvas.
- Store image files under the configured upload directory.
- Store only image paths and crop coordinates in the DB.
- Image search test does not affect meal creation or strategy generation.

