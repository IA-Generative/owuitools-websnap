"""Structured data models for the extraction pipeline."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ExtractionStage(str, Enum):
    FETCH = "fetch"
    PARSE = "parse"
    PDF = "pdf"
    IMAGE_ANALYSIS = "image_analysis"
    BROWSER = "browser"
    ENRICHMENT = "enrichment"


class ExtractionError(BaseModel):
    stage: ExtractionStage
    message: str
    recoverable: bool


class ExtractionResult(BaseModel):
    ok: bool
    markdown: str
    metadata: dict = Field(default_factory=dict)
    errors: list[ExtractionError] = Field(default_factory=list)


class FetchResult(BaseModel):
    status_code: int
    final_url: str
    content_type: str
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class AuthDetectionResult(BaseModel):
    is_auth_wall: bool
    signals: list[str] = Field(default_factory=list)
    score: int = 0


class ImageAnalysis(BaseModel):
    image_url: str
    description: str = ""
    visible_text: str = ""
    relevance: str = ""
    alt_text: str = ""
    error: str | None = None


class ParsedContent(BaseModel):
    title: str = "Untitled"
    content: str = ""
    headings: list[str] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    images: list[dict[str, str]] = Field(default_factory=list)
    language: str = "unknown"
    method: str = "trafilatura"
