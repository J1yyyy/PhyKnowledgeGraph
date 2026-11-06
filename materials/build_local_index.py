"""校验实体映射并为初中物理知识实体构建可复用的 NumPy 向量索引。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.question_locator import (  # noqa: E402
    CORPUS_INSTRUCTION,
    INDEX_FILE,
    INDEX_FILTER_VERSION,
    PROJECT_ID,
    QUERY_INSTRUCTION,
    QuestionLocatorError,
    SOURCE_FILE,
    TEXT_FORMAT_VERSION,
    embed_text,
    entity_text,
    is_searchable_entity,
    load_ai_settings,
    source_fingerprint,
)
from materials.import_phykgraph_json import CONFIG_FILE as NEO4J_CONFIG_FILE, validate_graph  # noqa: E402


NEO4J_LABEL = "JuniorPhysics2024"
PARTIAL_INDEX_FILE = INDEX_FILE.with_name("junior_physics_embeddings.partial.npz")
LEGACY_INDEX_FILE = ROOT / "data" / "generated" / "junior_demo_embeddings.npz"
INDEX_BACKUP_FILE = INDEX_FILE.with_name("junior_physics_embeddings.before-semantic.npz")


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
        "index_filter_version": INDEX_FILTER_VERSION,
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


def load_reusable_vectors(entities: list[dict], settings) -> dict[str, np.ndarray]:
    """按实体 ID 和原始知识文本复用向量，JSON 仅增加关系时不重复付费编码。"""
    expected = {
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "text_format_version": TEXT_FORMAT_VERSION,
        "corpus_instruction": CORPUS_INSTRUCTION,
        "query_instruction": QUERY_INSTRUCTION,
    }
    by_id = {entity["id"]: entity for entity in entities}
    reusable = {}
    for path in (INDEX_FILE, LEGACY_INDEX_FILE):
        if not path.exists():
            continue
        try:
            with np.load(path, allow_pickle=False) as stored:
                old_metadata = json.loads(str(stored["metadata"].item()))
                old_ids = stored["source_ids"].tolist()
                old_full_ids = stored["ids"].tolist() if path == INDEX_FILE else None
                old_texts = stored["texts"].tolist()
                old_vectors = stored["vectors"].astype(np.float32)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            print(f"{path.name} 无法读取，不复用其中向量：{type(error).__name__}")
            continue
        required = dict(expected)
        if path == INDEX_FILE:
            required.update({"project_id": PROJECT_ID, "index_filter_version": INDEX_FILTER_VERSION})
        if any(old_metadata.get(key) != value for key, value in required.items()):
            print(f"{path.name} 模型或编码配置不匹配，不复用其中向量")
            continue
        if (old_vectors.shape != (len(old_ids), settings.embedding_dimensions)
                or len(old_texts) != len(old_ids) or len(set(old_ids)) != len(old_ids)
                or (old_full_ids is not None and old_full_ids != [f"{PROJECT_ID}:{source_id}" for source_id in old_ids])
                or not np.isfinite(old_vectors).all() or not np.linalg.norm(old_vectors, axis=1).all()):
            print(f"{path.name} 向量或知识文本不完整，不复用其中向量")
            continue
        before = len(reusable)
        for source_id, knowledge_text, vector in zip(old_ids, old_texts, old_vectors):
            if source_id in by_id and knowledge_text == entity_text(by_id[source_id]):
                reusable.setdefault(source_id, vector)
        print(f"{path.name} 新增可安全复用 {len(reusable) - before} 个知识实体")
    return reusable


def reuse_index_without_api() -> None:
    """关系变化后只更新完整 JSON 指纹；缺任一实体向量即停止，绝不调用嵌入 API。"""
    data = validate_graph(json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig")))
    entities = [entity for entity in data["entities"] if is_searchable_entity(entity)]
    settings = load_ai_settings(require_key=False)
    reusable = load_reusable_vectors(entities, settings)
    if len(reusable) != len(entities) or not INDEX_FILE.exists():
        raise ValueError(f"仅复用模式需要现有索引覆盖全部 {len(entities)} 个知识实体；当前可复用 {len(reusable)} 个，不调用付费 API")
    if not INDEX_BACKUP_FILE.exists():
        shutil.copy2(INDEX_FILE, INDEX_BACKUP_FILE)
    metadata = index_metadata(settings, len(entities))
    metadata["created_at"] = datetime.now(timezone.utc).isoformat()
    save_index(INDEX_FILE, entities, [reusable[entity["id"]] for entity in entities], metadata)
    print(f"PASS：零 API 调用，复用 {len(entities)} 个知识实体向量；原索引备份为 {INDEX_BACKUP_FILE.name}")


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
    verify_neo4j_ids({f"{PROJECT_ID}:{entity['id']}" for entity in data["entities"]})
    entities = [entity for entity in data["entities"] if is_searchable_entity(entity)]

    settings = load_ai_settings(require_key=True)
    metadata = index_metadata(settings, len(entities))
    vectors = load_checkpoint(entities, metadata)
    reusable = load_reusable_vectors(entities, settings)
    remaining_calls = sum(entity["id"] not in reusable for entity in entities[len(vectors):])
    print(
        f"本次预计调用付费嵌入 API {remaining_calls} 次：模型={settings.embedding_model}，"
        f"维度={settings.embedding_dimensions}；共索引 {len(entities)} 个知识实体，不编码教材目录。"
    )
    for index, entity in enumerate(entities[len(vectors):], start=len(vectors) + 1):
        # 单个付费请求最多重试三次；每个实体完成后保存断点，避免中断后重复付费。
        if entity["id"] in reusable:
            vector = reusable[entity["id"]]
        else:
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
    parser.add_argument("--reuse-only", action="store_true", help="仅复用全部现有向量并更新索引指纹；缺失时停止，不调用 API")
    parser.add_argument("--yes", action="store_true", help="确认执行尚未复用的知识实体付费嵌入调用")
    args = parser.parse_args()
    try:
        if sum((args.verify_only, args.reuse_only, args.yes)) > 1:
            parser.error("--verify-only、--reuse-only 和 --yes 只能选择一个")
        data = validate_graph(json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig")))
        expected = {f"{PROJECT_ID}:{entity['id']}" for entity in data["entities"]}
        if args.verify_only:
            verify_neo4j_ids(expected)
            return
        if args.reuse_only:
            reuse_index_without_api()
            return
        if not args.yes:
            parser.error("构建索引会调用付费嵌入 API；确认后请增加 --yes")
        build_index()
    except (ValueError, OSError, QuestionLocatorError) as error:
        parser.exit(1, f"失败：{error}\n")


if __name__ == "__main__":
    main()
