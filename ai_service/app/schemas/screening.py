from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScreeningAnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    answer: str
    source: str
    updated_at: datetime


class ScreeningAnswerWrite(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(max_length=5000, description="Empty removes the saved answer")
    source: str = Field(default="user", pattern="^(user|suggested)$")
