from pydantic import BaseModel, Field, field_validator


class RagAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be blank")
        return stripped


class RagSource(BaseModel):
    post_id: int
    title: str
    excerpt: str
    score: float | None = None


class RagAskResponse(BaseModel):
    answer: str
    sources: list[RagSource]
