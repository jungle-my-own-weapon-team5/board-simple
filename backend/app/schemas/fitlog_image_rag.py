from pydantic import BaseModel


class ImageRagCandidateRead(BaseModel):
    food_name: str
    confidence: float
    estimated_calories: int
    carbs_g: float
    protein_g: float
    fat_g: float
    notes: list[str]


class ImageRagSearchResponse(BaseModel):
    query_handled: bool
    mode: str
    action: str | None = None
    accepted_food_name: str | None = None
    training_candidate_required: bool = False
    top_k: list[ImageRagCandidateRead]
