from pydantic import BaseModel


class TagRead(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}
