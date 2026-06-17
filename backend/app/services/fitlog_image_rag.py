"""Image-to-food orchestration boundary for FitLog.

The intended flow is:
1. classify uploaded food image with ResNet
2. accept high-confidence labels automatically
3. ask the user to confirm medium-confidence labels
4. store low-confidence images as training candidates
5. use the accepted label as text for nutrition lookup or text RAG
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.fitlog import MealFoodItemInput
from app.services.fitlog import get_or_create_nutrition_estimate
from app.services.fitlog_food_classifier import FoodClassificationResult, classify_food_image, classify_food_image_placeholder


@dataclass(frozen=True)
class ImageRagCandidate:
    food_name: str
    confidence: float
    estimated_calories: int
    carbs_g: float
    protein_g: float
    fat_g: float
    notes: list[str]


@dataclass(frozen=True)
class ImageRagDecision:
    query_handled: bool
    mode: str
    action: str
    accepted_food_name: str | None
    candidates: list[ImageRagCandidate]
    training_candidate_required: bool


def _nutrition_from_food_name(db: Session, food_name: str, confidence: float) -> ImageRagCandidate:
    """Resolve classified food label to cached or estimated nutrition."""
    item = get_or_create_nutrition_estimate(
        db,
        MealFoodItemInput(
            name=food_name,
            portion_text="1인분",
        ),
    )
    return ImageRagCandidate(
        food_name=item.name,
        confidence=confidence,
        estimated_calories=item.calories,
        carbs_g=item.carbs_g,
        protein_g=item.protein_g,
        fat_g=item.fat_g,
        notes=["Nutrition resolved from classifier label."],
    )


def classify_and_route_image_placeholder(db: Session) -> ImageRagDecision:
    """Return a fixed classification decision until ResNet is implemented."""
    classification = classify_food_image_placeholder()
    return route_classification_result(db, classification)


def classify_and_route_image(db: Session, image_bytes: bytes, top_k: int | None = None) -> ImageRagDecision:
    """Classify an uploaded image and route it by confidence."""
    settings = get_settings()
    classification = classify_food_image(image_bytes, top_k or settings.food_classifier_top_k)
    return route_classification_result(db, classification)


def route_classification_result(db: Session, classification: FoodClassificationResult) -> ImageRagDecision:
    """Choose the next action from classifier confidence."""
    settings = get_settings()
    top_candidate = classification.top_candidates[0] if classification.top_candidates else None
    if top_candidate is None:
        return ImageRagDecision(
            query_handled=False,
            mode="classification_placeholder",
            action="manual_label_required",
            accepted_food_name=None,
            candidates=[],
            training_candidate_required=True,
        )

    candidates = [
        _nutrition_from_food_name(db, candidate.food_name, candidate.confidence)
        for candidate in classification.top_candidates
    ]

    if top_candidate.confidence >= settings.food_classifier_auto_accept_threshold:
        return ImageRagDecision(
            query_handled=True,
            mode=classification.model_name,
            action="auto_accept_label",
            accepted_food_name=top_candidate.food_name,
            candidates=candidates,
            training_candidate_required=False,
        )

    if top_candidate.confidence >= settings.food_classifier_user_confirm_threshold:
        return ImageRagDecision(
            query_handled=True,
            mode=classification.model_name,
            action="user_confirm_label",
            accepted_food_name=None,
            candidates=candidates,
            training_candidate_required=True,
        )

    return ImageRagDecision(
        query_handled=True,
        mode=classification.model_name,
        action="manual_label_required",
        accepted_food_name=None,
        candidates=candidates,
        training_candidate_required=True,
    )


def build_text_rag_query(food_name: str) -> str:
    """Build a text query from an accepted image classifier label."""
    return f"{food_name} nutrition diet strategy portion control"


def search_food_image_placeholder() -> list[ImageRagCandidate]:
    """Compatibility wrapper for the existing placeholder endpoint."""
    return [
        ImageRagCandidate(
            food_name="ramen",
            confidence=0.92,
            estimated_calories=500,
            carbs_g=78,
            protein_g=10,
            fat_g=16,
            notes=["Placeholder result for image classification wiring."],
        )
    ]
