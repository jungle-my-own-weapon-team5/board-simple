"""ResNet food classifier boundary for FitLog.

This service should own:
- loading the fine-tuned ResNet-34 classifier once
- preprocessing uploaded images
- returning top-k food labels with confidence scores

It does not produce OpenAI embeddings. The accepted food label can later be
used as text for nutrition lookup, LLM estimation, or text RAG.
"""

from dataclasses import dataclass
from io import BytesIO
from functools import lru_cache
from typing import Any

from app.core.config import get_settings


FOOD_CLASSIFIER_MODEL_NAME = "resnet34_food_classifier"


@dataclass(frozen=True)
class FoodLabelCandidate:
    food_name: str
    label: str
    confidence: float


@dataclass(frozen=True)
class FoodClassificationResult:
    model_name: str
    top_candidates: list[FoodLabelCandidate]


@dataclass(frozen=True)
class FoodClassifierBundle:
    model: Any
    transform: Any
    classes: list[str]
    device: Any


@lru_cache(maxsize=1)
def get_resnet34_food_classifier() -> FoodClassifierBundle:
    """Load and cache the fine-tuned ResNet-34 food classifier."""
    settings = get_settings()

    import torch
    from torchvision.models import ResNet34_Weights, resnet34

    if settings.food_classifier_device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(settings.food_classifier_device)

    ckpt = torch.load(settings.food_classifier_model_path, map_location="cpu")
    classes = ckpt["classes"]
    num_classes = len(classes)
    weights = ResNet34_Weights.DEFAULT
    transform = weights.transforms()
    model = resnet34(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
    model.load_state_dict(ckpt["model_state_dict"])
    model = model.to(device)
    model.eval()
    return FoodClassifierBundle(model, transform, classes, device)


def classify_food_image(image_bytes: bytes, top_k: int = 3) -> FoodClassificationResult:
    """Classify uploaded image bytes into top-k food labels."""
    import torch
    from PIL import Image

    settings = get_settings()
    bundle = get_resnet34_food_classifier()
    requested_top_k = top_k or settings.food_classifier_top_k
    k = max(1, min(requested_top_k, len(bundle.classes)))

    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    tensor = bundle.transform(image).unsqueeze(0).to(bundle.device)

    with torch.no_grad():
        logits = bundle.model(tensor)
        probabilities = torch.softmax(logits, dim=1)[0]
        confidence_values, indices = torch.topk(probabilities, k)

    candidates = [
        FoodLabelCandidate(
            food_name=bundle.classes[index],
            label=bundle.classes[index],
            confidence=float(confidence),
        )
        for confidence, index in zip(confidence_values.tolist(), indices.tolist())
    ]

    return FoodClassificationResult(
        model_name=FOOD_CLASSIFIER_MODEL_NAME,
        top_candidates=candidates,
    )


def classify_food_image_placeholder() -> FoodClassificationResult:
    """Return fixed candidates until the ResNet classifier is implemented."""
    return FoodClassificationResult(
        model_name=f"{FOOD_CLASSIFIER_MODEL_NAME}:placeholder",
        top_candidates=[
            FoodLabelCandidate(food_name="ramen", label="ramen", confidence=0.92),
            FoodLabelCandidate(food_name="kimchi_stew", label="kimchi_stew", confidence=0.38),
            FoodLabelCandidate(food_name="bibimbap", label="bibimbap", confidence=0.21),
        ],
    )
