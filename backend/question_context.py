"""从题目候选的真实关系中挑选少量可解释的图谱上下文。"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.question_locator import PROJECT_ID, QuestionAnalysis


# 教材目录关系只用于章节定位；题目上下文优先展示知识间的明确语义关系。
RELATION_WEIGHTS = {
    "PREREQUISITE": 3,
    "APPLICABLE_UNDER": 3,
    "CONTAINS_VARIABLE": 3,
    "DESCRIBED_BY": 3,
    "EXPLAINS": 3,
    "MODELLED_BY": 3,
    "VERIFIES": 3,
    "MEASURED_USING": 3,
    "MEASURES": 3,
    "PARENT_CHILD": 2,
    "IS_A": 2,
    "EMPLOY_METHOD": 2,
    "APPLIED_IN": 2,
    "RELATED_TO": 1,
    "RELATES_TO": 1,
}
MAX_SUPPORT_NODES = 8


class ContextCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=160)
    score: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)

    @field_validator("id")
    @classmethod
    def valid_project_id(cls, value: str) -> str:
        if not value.startswith(f"{PROJECT_ID}:"):
            raise ValueError("候选 ID 前缀与当前图谱不一致")
        return value


class QuestionContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[ContextCandidate] = Field(min_length=1, max_length=5)
    analysis: QuestionAnalysis
    coverage_sufficient: bool | None = None

    @model_validator(mode="after")
    def unique_candidates(self) -> "QuestionContextRequest":
        ids = [item.id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("候选 ID 不能重复")
        return self


def select_question_context(request: QuestionContextRequest, rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    """始终保留所有候选；支持节点须与解析文本吻合或同时连接多个候选。"""
    candidate_ids = [item.id for item in request.candidates]
    candidate_set = set(candidate_ids)
    similarities = {item.id: (item.score + 1) / 2 if item.score is not None else 0.5 for item in request.candidates}
    terms = [term.strip().casefold() for term in request.analysis.candidate_concepts if len(term.strip()) >= 2]
    retrieval_text = request.analysis.retrieval_text.casefold()
    support_links: dict[str, set[str]] = defaultdict(set)
    support_scores: dict[str, float] = defaultdict(float)
    support_names: dict[str, str] = {}
    edges: dict[tuple[str, str, str], dict[str, str]] = {}

    for row in rows:
        candidate_id = row["candidate_id"]
        neighbor_id = row["neighbor_id"]
        relation = row["relation_type"]
        if candidate_id not in candidate_set or relation not in RELATION_WEIGHTS or neighbor_id == candidate_id:
            continue
        edge = {
            "from": row["from"], "to": row["to"],
            "relation_type": relation, "label": row["label"],
        }
        edges[(edge["from"], relation, edge["to"])] = edge
        if neighbor_id not in candidate_set:
            support_links[neighbor_id].add(candidate_id)
            support_names[neighbor_id] = row["neighbor_label"].casefold()
            support_scores[neighbor_id] += RELATION_WEIGHTS[relation] * similarities[candidate_id]

    support_ids: list[str] = []
    if request.coverage_sufficient is not False:
        ranked = []
        for node_id, linked_candidates in support_links.items():
            name = support_names[node_id]
            concept_match = any(term in name or name in term for term in terms)
            text_match = len(name) >= 2 and name in retrieval_text
            shared = len(linked_candidates) >= 2
            if not (concept_match or text_match or shared):
                continue
            relevance = support_scores[node_id] + 3 * concept_match + 2 * text_match + 3 * shared
            if isfinite(relevance):
                ranked.append((-relevance, node_id))
        ranked.sort()
        support_ids = [node_id for _, node_id in ranked[:MAX_SUPPORT_NODES]]

    selected_ids = candidate_ids + support_ids
    selected_set = set(selected_ids)
    selected_edges = [edge for edge in edges.values() if edge["from"] in selected_set and edge["to"] in selected_set]
    selected_edges.sort(key=lambda edge: (edge["from"], edge["to"], edge["relation_type"]))
    return selected_ids, selected_edges
