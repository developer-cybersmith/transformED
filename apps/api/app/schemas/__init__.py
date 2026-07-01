from typing import Literal

from pydantic import BaseModel, Field


class SectionBoundary(BaseModel):
    id: str
    title: str
    level: Literal["chapter", "section", "topic"]
    body: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)


class DocumentStructure(BaseModel):
    sections: list[SectionBoundary] = Field(min_length=1)
