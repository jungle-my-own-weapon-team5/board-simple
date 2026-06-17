"""Future SQLAlchemy models for FitLog image classification.

Expected table:
- food_image_training_candidates
  - user_id
  - meal_log_id
  - image_path
  - predicted_label
  - predicted_confidence
  - confirmed_label
  - status

Optional later table:
- food_image_embeddings
  - image_path
  - food_name
  - embedding vector(512)
  - source
  - created_at

Keep this file separate from app.models.fitlog until the migration is added.
"""
