"""题目解析与本地向量检索；外部模型只在后端调用。"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "data" / "demo_junior_physics.json"
INDEX_FILE = ROOT / "data" / "generated" / "junior_demo_embeddings.npz"
EVAL_FILE = ROOT / "data" / "question_eval.json"
EXAMPLE_CONFIG_FILE = ROOT / "backend" / "ai.example.json"
LOCAL_CONFIG_FILE = ROOT / "backend" / "ai.local.json"

TEXT_FORMAT_VERSION = "entity-name-type-v1"
CORPUS_INSTRUCTION = (
    "Target_modality: text.\n"
    "Instruction: Represent the physics knowledge graph entity for semantic retrieval. Passage:"
)
QUERY_INSTRUCTION = (
    "Target_modality: text.\n"
    "Instruction: Retrieve physics knowledge graph entities relevant to the physics question. Query:"
)


class QuestionLocatorError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class QuestionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=300)
    known_quantities: list[str] = Field(default_factory=list, max_length=20)
    target_quantity: str = Field(min_length=1, max_length=200)
    candidate_concepts: list[str] = Field(default_factory=list, max_length=20)
    retrieval_text: str = Field(min_length=1, max_length=1000)

    @field_validator("domain", "task", "target_quantity", "retrieval_text")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("known_quantities", "candidate_concepts")
    @classmethod
    def clean_text_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("列表元素必须是字符串")
            value = value.strip()
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned


class LocateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=5000)
    mode: Literal["live_api", "offline_example"] = "live_api"
    example_id: str | None = Field(default=None, max_length=80)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("题目不能为空")
        return value


@dataclass(frozen=True)
class AISettings:
    base_url: str
    api_key: str
    llm_model: str
    embedding_model: str
    embedding_dimensions: int
    timeout_seconds: float
    coverage_threshold: float | None


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuestionLocatorError("AI_CONFIG_INVALID", f"AI 配置文件无效：{path.name}") from error
    if not isinstance(data, dict):
        raise QuestionLocatorError("AI_CONFIG_INVALID", f"AI 配置文件必须是 JSON 对象：{path.name}")
    return data


def load_ai_settings(require_key: bool = True) -> AISettings:
    config = _read_config(EXAMPLE_CONFIG_FILE)
    config.update(_read_config(LOCAL_CONFIG_FILE))
    values = {
        "base_url": os.getenv("ARK_BASE_URL", config.get("base_url")),
        "api_key": os.getenv("ARK_API_KEY", config.get("api_key")),
        "llm_model": os.getenv("ARK_LLM_MODEL", config.get("llm_model")),
        "embedding_model": os.getenv("ARK_EMBEDDING_MODEL", config.get("embedding_model")),
        "embedding_dimensions": os.getenv("ARK_EMBEDDING_DIMENSIONS", config.get("embedding_dimensions")),
        "timeout_seconds": os.getenv("ARK_TIMEOUT_SECONDS", config.get("timeout_seconds", 30)),
        "coverage_threshold": os.getenv("ARK_COVERAGE_THRESHOLD", config.get("coverage_threshold")),
    }
    missing = [key for key in ("base_url", "llm_model", "embedding_model") if not values[key]]
    if require_key and not values["api_key"]:
        missing.append("api_key")
    if missing:
        raise QuestionLocatorError(
            "AI_CONFIG_MISSING",
            f"缺少 AI 配置：{', '.join(missing)}；请填写 backend/ai.local.json",
            503,
        )
    try:
        dimensions = int(values["embedding_dimensions"])
        timeout = float(values["timeout_seconds"])
        threshold = None if values["coverage_threshold"] in (None, "") else float(values["coverage_threshold"])
    except (TypeError, ValueError) as error:
        raise QuestionLocatorError("AI_CONFIG_INVALID", "AI 配置中的维度、超时或阈值格式错误") from error
    if dimensions <= 0 or timeout <= 0 or (threshold is not None and not -1 <= threshold <= 1):
        raise QuestionLocatorError("AI_CONFIG_INVALID", "AI 配置中的维度、超时或阈值超出有效范围")
    return AISettings(
        base_url=str(values["base_url"]).rstrip("/"),
        api_key=str(values["api_key"] or ""),
        llm_model=str(values["llm_model"]),
        embedding_model=str(values["embedding_model"]),
        embedding_dimensions=dimensions,
        timeout_seconds=timeout,
        coverage_threshold=threshold,
    )


def source_fingerprint(path: Path = SOURCE_FILE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entity_text(entity: dict[str, Any]) -> str:
    return f"名称：{entity['name']}\n类型：{entity['type']}"


def _post_json(
    url: str,
    payload: dict[str, Any],
    settings: AISettings,
    attempts: int = 1,
) -> dict[str, Any]:
    """调用方舟接口；批量建索引可重试瞬时网络错误，且从不回显鉴权信息。"""
    body = ""
    attempts = max(1, attempts)
    for attempt in range(attempts):
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.timeout_seconds) as response:
                body = response.read().decode("utf-8")
            break
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            raise QuestionLocatorError("AI_HTTP_ERROR", f"火山方舟接口返回 HTTP {error.code}：{detail}", 502) from error
        except (URLError, TimeoutError, OSError) as error:
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            error_name = type(error).__name__
            raise QuestionLocatorError(
                "AI_REQUEST_FAILED",
                f"火山方舟接口连接失败或超时（{error_name}，已尝试 {attempts} 次）",
                504,
            ) from error
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise QuestionLocatorError("AI_RESPONSE_INVALID", "火山方舟接口返回了非法 JSON", 502) from error
    if not isinstance(result, dict):
        raise QuestionLocatorError("AI_RESPONSE_INVALID", "火山方舟接口返回格式错误", 502)
    return result


def parse_question(question: str, settings: AISettings) -> tuple[QuestionAnalysis, dict[str, Any]]:
    schema = QuestionAnalysis.model_json_schema()
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你只负责解析初中物理题，不解题。严格按 JSON Schema 提取领域、任务、已知量、待求量、"
                    "可能相关的物理概念，并生成适合知识点语义检索的简短 retrieval_text。"
                    "不要生成图谱实体 ID，不要编造题目没有给出的数值。"
                ),
            },
            {"role": "user", "content": question},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "question_analysis", "strict": True, "schema": schema},
        },
    }
    response = _post_json(f"{settings.base_url}/chat/completions", payload, settings)
    try:
        content = response["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        analysis = QuestionAnalysis.model_validate(parsed)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as error:
        raise QuestionLocatorError("LLM_OUTPUT_INVALID", "LLM 返回内容未通过结构化校验", 502) from error
    return analysis, response.get("usage", {})


def embed_text(
    text: str,
    settings: AISettings,
    instruction: str,
    attempts: int = 1,
) -> tuple[np.ndarray, dict[str, Any]]:
    payload = {
        "model": settings.embedding_model,
        "instructions": instruction,
        "encoding_format": "float",
        "dimensions": settings.embedding_dimensions,
        "input": [{"type": "text", "text": text}],
    }
    response = _post_json(f"{settings.base_url}/embeddings/multimodal", payload, settings, attempts=attempts)
    try:
        data = response["data"]
        embedding = data[0]["embedding"] if isinstance(data, list) else data["embedding"]
        vector = np.asarray(embedding, dtype=np.float32)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise QuestionLocatorError("EMBEDDING_OUTPUT_INVALID", "嵌入接口没有返回有效向量", 502) from error
    if vector.ndim != 1 or vector.size != settings.embedding_dimensions or not np.isfinite(vector).all():
        raise QuestionLocatorError("EMBEDDING_OUTPUT_INVALID", "嵌入向量维度或数值无效", 502)
    return vector, response.get("usage", {})


class _IndexCache:
    path: Path | None = None
    mtime_ns: int | None = None
    data: dict[str, Any] | None = None


_index_cache = _IndexCache()


def load_index(settings: AISettings) -> dict[str, Any]:
    if not INDEX_FILE.exists():
        raise QuestionLocatorError(
            "INDEX_MISSING",
            "本地向量索引不存在，请先运行 materials/build_local_index.py",
            503,
        )
    stat = INDEX_FILE.stat()
    if _index_cache.path == INDEX_FILE and _index_cache.mtime_ns == stat.st_mtime_ns and _index_cache.data:
        data = _index_cache.data
    else:
        try:
            with np.load(INDEX_FILE, allow_pickle=False) as stored:
                data = {key: stored[key].copy() for key in stored.files}
            metadata = json.loads(str(data["metadata"].item()))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise QuestionLocatorError("INDEX_INVALID", "本地向量索引损坏，请重新构建", 503) from error
        data["metadata_dict"] = metadata
        _index_cache.path = INDEX_FILE
        _index_cache.mtime_ns = stat.st_mtime_ns
        _index_cache.data = data
    metadata = data["metadata_dict"]
    expected = {
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "source_fingerprint": source_fingerprint(),
        "text_format_version": TEXT_FORMAT_VERSION,
        "corpus_instruction": CORPUS_INSTRUCTION,
        "query_instruction": QUERY_INSTRUCTION,
    }
    mismatches = [key for key, value in expected.items() if metadata.get(key) != value]
    if mismatches:
        raise QuestionLocatorError(
            "INDEX_MISMATCH",
            f"本地向量索引与当前配置不匹配（{', '.join(mismatches)}），请重新构建",
            503,
        )
    vectors = data.get("vectors")
    if vectors is None or vectors.ndim != 2 or vectors.shape[1] != settings.embedding_dimensions:
        raise QuestionLocatorError("INDEX_INVALID", "本地向量索引维度无效，请重新构建", 503)
    return data


def search_index(query_vector: np.ndarray, settings: AISettings, limit: int = 5) -> tuple[list[dict[str, Any]], bool | None, str | None]:
    index = load_index(settings)
    vectors = index["vectors"].astype(np.float32, copy=False)
    query_norm = float(np.linalg.norm(query_vector))
    vector_norms = np.linalg.norm(vectors, axis=1)
    if query_norm == 0 or np.any(vector_norms == 0):
        raise QuestionLocatorError("INDEX_INVALID", "索引或查询中包含零向量，请重新构建", 503)
    scores = vectors @ query_vector / (vector_norms * query_norm)
    order = np.argsort(-scores, kind="stable")[: max(1, min(limit, 5))]
    candidates = [
        {
            "id": str(index["ids"][i]),
            "source_id": str(index["source_ids"][i]),
            "name": str(index["names"][i]),
            "type": str(index["types"][i]),
            "score": round(float(scores[i]), 6),
        }
        for i in order
    ]
    if not candidates:
        return [], False, "本地图谱没有可返回的候选知识点"
    if settings.coverage_threshold is None:
        return candidates, None, "未配置覆盖阈值，请结合候选内容人工判断"
    sufficient = candidates[0]["score"] >= settings.coverage_threshold
    return candidates, sufficient, None if sufficient else "最高相似度低于覆盖阈值，当前图谱可能未覆盖该题"


@lru_cache(maxsize=1)
def load_examples() -> list[dict[str, Any]]:
    try:
        examples = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuestionLocatorError("EXAMPLES_INVALID", "离线示例文件缺失或格式错误", 500) from error
    if not isinstance(examples, list):
        raise QuestionLocatorError("EXAMPLES_INVALID", "离线示例必须是数组", 500)
    return examples


def locate_offline_example(request: LocateQuestionRequest) -> dict[str, Any]:
    example = next((item for item in load_examples() if item.get("id") == request.example_id), None)
    if not example or request.question != example.get("question"):
        raise QuestionLocatorError("OFFLINE_EXAMPLE_NOT_FOUND", "离线模式只接受内置示例题原文", 400)
    entities = {item["id"]: item for item in json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig"))["entities"]}
    candidates = []
    for entity_id in example.get("expected_entity_ids", []):
        source_id = entity_id.removeprefix("junior_demo:")
        entity = entities.get(source_id)
        if not entity:
            raise QuestionLocatorError("EXAMPLES_INVALID", f"离线示例引用了不存在的实体：{entity_id}", 500)
        candidates.append({
            "id": entity_id,
            "source_id": source_id,
            "name": entity["name"],
            "type": entity["type"],
            "score": None,
        })
    covered = bool(example.get("coverage_expected"))
    return {
        "project_id": "junior_demo",
        "source": "offline_example",
        "retrieval_status": "not_run",
        "analysis": QuestionAnalysis.model_validate(example["analysis"]).model_dump(),
        "candidates": candidates,
        "coverage_sufficient": covered,
        "coverage_message": None if covered else "人工标注为当前图谱未覆盖；未调用 LLM 或嵌入 API",
        "index": None,
        "usage": None,
    }


def locate_live(question: str) -> dict[str, Any]:
    settings = load_ai_settings(require_key=True)
    analysis, llm_usage = parse_question(question, settings)
    query_vector, embedding_usage = embed_text(analysis.retrieval_text, settings, QUERY_INSTRUCTION)
    candidates, sufficient, message = search_index(query_vector, settings)
    index = load_index(settings)
    metadata = index["metadata_dict"]
    return {
        "project_id": "junior_demo",
        "source": "live_api",
        "retrieval_status": "completed",
        "analysis": analysis.model_dump(),
        "candidates": candidates,
        "coverage_sufficient": sufficient,
        "coverage_message": message,
        "index": {
            "embedding_model": metadata["embedding_model"],
            "dimension": metadata["embedding_dimensions"],
            "source_fingerprint": metadata["source_fingerprint"],
        },
        "usage": {"llm": llm_usage, "embedding": embedding_usage},
    }
