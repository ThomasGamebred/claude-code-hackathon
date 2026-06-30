"""Pydantic response models — shape matches frontend/src/api/types.ts exactly."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceInfo(BaseModel):
    name: str
    row_count: int
    quality_score: float
    last_ingested_at: str
    anomaly_count: int
    notes: str | None = None


class CustomerSummary(BaseModel):
    id: str
    full_name: str
    city: str | None = None
    region: str | None = None
    n_sources: int
    record_confidence: float


class FieldProvenance(BaseModel):
    field: str
    value: str | None = None
    source: str
    confidence: float
    rationale: str | None = None


class SourceContribution(BaseModel):
    source: str
    source_id: str
    source_row: int
    ingested_at: str
    fields: dict[str, str | None]
    field_quality_flags: list[str]


class CustomerDetail(BaseModel):
    id: str
    full_name: str
    city: str | None = None
    region: str | None = None
    birth_year: int | None = None
    n_sources: int
    record_confidence: float
    fields: list[FieldProvenance]
    contributions: list[SourceContribution]


class ReviewSide(BaseModel):
    source: str
    source_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    dob: str | None = None


class ReviewPair(BaseModel):
    id: str
    score: float
    left: ReviewSide
    right: ReviewSide
    reason: str


class ReviewDecision(BaseModel):
    decision: str
    note: str | None = None


class QualityCheck(BaseModel):
    name: str
    level: str
    status: str
    message: str
    ran_at: str


class LineageNode(BaseModel):
    id: str
    kind: str
    label: str
    meta: dict[str, Any] | None = None


class LineageEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_node: str = Field(alias="from", serialization_alias="from")
    to: str


class LineageGraph(BaseModel):
    root: str
    nodes: list[LineageNode]
    edges: list[LineageEdge]
