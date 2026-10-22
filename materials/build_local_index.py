"""校验实体映射并为 junior_demo 构建可复用的 NumPy 向量索引。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.question_locator import (  # noqa: E402
    CORPUS_INSTRUCTION,
    INDEX_FILE,
    QUERY_INSTRUCTION,
    QuestionLocatorError,
    SOURCE_FILE,
    TEXT_FORMAT_VERSION,
    embed_text,
    entity_text,
    load_ai_settings,
    source_fingerprint,
)
from materials.import_phykgraph_json import CONFIG_FILE as NEO4J_CONFIG_FILE, validate_graph  # noqa: E402


PROJECT_ID = "junior_demo"
NEO4J_LABEL = "DemoJuniorPhysics"
PARTIAL_INDEX_FILE = INDEX_FILE.with_name("junior_demo_embeddings.partial.npz")


def load_neo4j_config() -> dict[str, str]:
    local = json.loads(NEO4J_CONFIG_FILE.read_text(encoding="utf-8")) if NEO4J_CONFIG_FILE.exists() else {}
    config = {
        "uri": os.getenv("NEO4J_URI", local.get("uri", "bolt://localhost:7687")),
        "user": os.getenv("NEO4J_USER", local.get("user", "neo4j")),
        "password": os.getenv("NEO4J_PASSWORD", local.get("password")),
        "database": os.getenv("NEO4J_DATABASE", local.get("database", "neo4j")),
    }
    if not config["password"]:
        raise ValueError("缺少 Neo4j 密码，请先配置 backend/neo4j.local.json")
    return config


def verify_neo4j_ids(expected_ids: set[str]) -> None:
    config = load_neo4j_config()
    with GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"])) as driver:
        driver.verify_connectivity()
        with driver.session(database=config["database"]) as session:
            records = session.run(f"MATCH (n:{NEO4J_LABEL}) RETURN n.id AS id, n.source_id AS source_id")
            actual = {record["id"]: record["source_id"] for record in records}
    actual_ids = set(actual)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    bad_source = sorted(entity_id for entity_id in expected_ids & actual_ids if actual[entity_id] != entity_id.split(":", 1)[1])
    if missing or extra or bad_source:
        details = []
        if missing:
            details.append(f"Neo4j 缺少 {len(missing)} 个 ID")
        if extra:
            details.append(f"Neo4j 多出 {len(extra)} 个 ID")
        if bad_source:
            details.append(f"source_id 不一致 {len(bad_source)} 个")
        raise ValueError("实体 ID 映射校验失败：" + "；".join(details))
    print(f"PASS：JSON 原 ID 与 Neo4j {PROJECT_ID}: 前缀映射一致（{len(expected_ids)} 个）")


def index_metadata(settings, entity_count: int) -> dict:
    """检查点与最终索引共用同一份元数据，防止跨模型或跨数据续跑。"""
    return {
        "project_id": PROJECT_ID,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "source_file": SOURCE_FILE.name,
        "source_fingerprint": source_fingerprint(),
        "entity_count": entity_count,
        "text_format_version": TEXT_FORMAT_VERSION,
        "corpus_instruction": CORPUS_INSTRUCTION,
        "query_instruction": QUERY_INSTRUCTION,
    }


def save_index(path: Path, entities: list[dict], vectors: list[np.ndarray], metadata: dict) -> None:
    """先写临时文件再替换，避免中断时留下损坏的索引或检查点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as output:
        np.savez_compressed(
            output,
            ids=np.asarray([f"{PROJECT_ID}:{entity['id']}" for entity in entities]),
            source_ids=np.asarray([entity["id"] for entity in entities]),
            names=np.asarray([entity["name"] for entity in entities]),
            types=np.asarray([entity["type"] for entity in entities]),
            texts=np.asarray([entity_text(entity) for entity in entities]),
            vectors=np.vstack(vectors).astype(np.float32, copy=False),
            metadata=np.asarray(json.dumps(metadata, ensure_ascii=False)),
        )
    temporary.replace(path)


def load_checkpoint(entities: list[dict], metadata: dict) -> list[np.ndarray]:
    if not PARTIAL_INDEX_FILE.exists():
        return []
    try:
        with np.load(PARTIAL_INDEX_FILE, allow_pickle=False) as stored:
            saved_metadata = json.loads(str(stored["metadata"].item()))
            saved_ids = stored["source_ids"].tolist()
            saved_vectors = stored["vectors"].astype(np.float32)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f"断点文件损坏，请删除后重试：{PARTIAL_INDEX_FILE}") from error
    expected_ids = [entity["id"] for entity in entities[: len(saved_ids)]]
    if saved_metadata != metadata or saved_ids != expected_ids or saved_vectors.shape != (len(saved_ids), metadata["embedding_dimensions"]):
        raise ValueError(f"断点文件与当前数据或模型不匹配，请删除后重试：{PARTIAL_INDEX_FILE}")
    print(f"发现可用断点：已完成 {len(saved_ids)}/{len(entities)}，从下一项继续")
    return [row for row in saved_vectors]


def build_index() -> None:
    data = validate_graph(json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig")))
    entities = data["entities"]
    verify_neo4j_ids({f"{PROJECT_ID}:{entity['id']}" for entity in entities})

    settings = load_ai_settings(require_key=True)
    print(
        f"即将调用付费嵌入 API {len(entities)} 次：模型={settings.embedding_model}，"
        f"维度={settings.embedding_dimensions}。节点向量生成后将写入本地索引并复用。"
    )
    metadata = index_metadata(settings, len(entities))
    vectors = load_checkpoint(entities, metadata)
    for index, entity in enumerate(entities[len(vectors):], start=len(vectors) + 1):
        # 单个请求最多重试三次；每次成功立即保存断点，避免网络中断后重复付费。
        vector, _ = embed_text(entity_text(entity), settings, CORPUS_INSTRUCTION, attempts=3)
        vectors.append(vector)
        save_index(PARTIAL_INDEX_FILE, entities[:index], vectors, metadata)
        if index == 1 or index % 10 == 0 or index == len(entities):
            print(f"向量化进度：{index}/{len(entities)}")
        time.sleep(0.1)

    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    metadata["created_at"] = datetime.now(timezone.utc).isoformat()
    save_index(INDEX_FILE, entities, vectors, metadata)
    PARTIAL_INDEX_FILE.unlink(missing_ok=True)
    print(f"PASS：索引已写入 {INDEX_FILE}，{matrix.shape[0]} 个实体，{matrix.shape[1]} 维")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="只校验 JSON 与 Neo4j ID，不调用嵌入 API")
    parser.add_argument("--yes", action="store_true", help="确认执行 101 次付费嵌入调用")
    args = parser.parse_args()
    try:
        data = validate_graph(json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig")))
        expected = {f"{PROJECT_ID}:{entity['id']}" for entity in data["entities"]}
        if args.verify_only:
            verify_neo4j_ids(expected)
            return
        if not args.yes:
            parser.error("构建索引会调用付费嵌入 API；确认后请增加 --yes")
        build_index()
    except (ValueError, OSError, QuestionLocatorError) as error:
        parser.exit(1, f"失败：{error}\n")


if __name__ == "__main__":
    main()
