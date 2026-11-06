"""用同一索引比较题目原文与已保存的 LLM 解析文本的 Top-5 检索。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from backend.question_locator import (
    INDEX_FILE,
    QUERY_INSTRUCTION,
    QuestionLocatorError,
    embed_text,
    load_ai_settings,
    load_index,
    search_index,
)
from materials.evaluate_question_locator import (
    ROOT,
    load_cases,
    new_run_path,
    save_run,
    score_case,
    select_cases,
    summarize,
    validate_cases,
)


DATASET = ROOT / "data" / "question_eval_50.json"


def project_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"结果文件无法读取或不是合法 JSON：{path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"结果文件不是 JSON 对象：{path}")
    return value


def validate_prior_run(prior: dict, cases: list[dict], dataset_sha: str, index: dict, index_mtime: float) -> None:
    """旧 LLM 结果必须来自相同题集、索引和顺序，才能与本次原文检索配对。"""
    ids = [case["id"] for case in cases]
    if prior.get("status") != "completed" or prior.get("mode") != "live_api":
        raise ValueError("旧 LLM 结果不是已完成的实时评测")
    if prior.get("dataset_sha256") != dataset_sha or prior.get("selected_case_ids") != ids:
        raise ValueError("旧 LLM 结果的题集或题目顺序不匹配")
    created = datetime.fromisoformat(prior["created_at_utc"])
    if index_mtime > created.timestamp():
        raise ValueError("当前索引晚于旧 LLM 结果，不能确认两组使用同一索引")
    metadata = index["metadata_dict"]
    expected_index = {
        "embedding_model": metadata["embedding_model"],
        "dimension": metadata["embedding_dimensions"],
        "source_fingerprint": metadata["source_fingerprint"],
    }
    indexed_ids = set(map(str, index["ids"]))
    rows = prior.get("results")
    if not isinstance(rows, list) or [row.get("id") for row in rows] != ids:
        raise ValueError("旧 LLM 结果缺题或顺序不匹配")
    for row in rows:
        if row.get("index") != expected_index:
            raise ValueError(f"{row['id']}：旧结果与当前索引标识不匹配")
        if not row.get("analysis", {}).get("retrieval_text", "").strip():
            raise ValueError(f"{row['id']}：旧结果缺少 LLM 检索文本")
        candidates = row.get("candidates", [])
        candidate_ids = [item["id"] for item in candidates]
        if not candidates or len(candidates) > 5 or len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError(f"{row['id']}：旧结果候选数量或 ID 无效")
        if not set(candidate_ids) <= indexed_ids:
            raise ValueError(f"{row['id']}：旧结果候选不在当前索引中")


def summarize_pairs(cases: list[dict], pairs: list[dict]) -> dict:
    by_id = {case["id"]: case for case in cases}
    arms = {}
    for arm in ("raw", "parsed"):
        rows = [
            {"id": pair["id"], "metrics": pair[arm]["metrics"], "coverage_sufficient": None}
            for pair in pairs
        ]
        arms[arm] = summarize(cases, rows)
    covered = [pair for pair in pairs if by_id[pair["id"]]["coverage"] == "covered"]
    outcomes = {"raw_better": [], "parsed_better": [], "tie": []}
    for pair in covered:
        raw_hit = pair["raw"]["metrics"]["hit_at_5"]
        parsed_hit = pair["parsed"]["metrics"]["hit_at_5"]
        key = "raw_better" if raw_hit and not parsed_hit else "parsed_better" if parsed_hit and not raw_hit else "tie"
        outcomes[key].append(pair["id"])
    return {"raw": arms["raw"], "parsed": arms["parsed"], "hit_at_5_pairs": outcomes}


def check_resume(record: dict, split: str, prior_sha: str, dataset_sha: str, index_sha: str, cases: list[dict]) -> None:
    ids = [case["id"] for case in cases]
    if record.get("status") == "completed" or record.get("mode") != "raw_vs_parsed":
        raise ValueError("只能续跑尚未完成的原文与解析文本对比")
    if (record.get("split"), record.get("prior_run_sha256"), record.get("dataset_sha256"), record.get("index_sha256")) != (
        split, prior_sha, dataset_sha, index_sha
    ):
        raise ValueError("题集、旧 LLM 结果或索引已变化，不能续跑")
    completed_ids = [item["id"] for item in record["results"]]
    if record.get("selected_case_ids") != ids or completed_ids != ids[:len(completed_ids)]:
        raise ValueError("已完成题目与当前分组顺序不一致")


def run_cases(cases: list[dict], prior_rows: list[dict], settings, record: dict, output: Path) -> None:
    """仅原文产生新嵌入调用；每道题两组结果成对保存，失败后从下一题续跑。"""
    done = len(record["results"])
    record["status"] = "running"
    record.pop("error", None)
    save_run(output, record)
    for case, prior in zip(cases[done:], prior_rows[done:]):
        try:
            vector, usage = embed_text(case["question"], settings, QUERY_INSTRUCTION)
            candidates, sufficient, message = search_index(vector, settings)
            parsed_candidates = prior["candidates"]
            pair = {
                "id": case["id"],
                "raw": {
                    "candidates": candidates,
                    "metrics": score_case(case, [item["id"] for item in candidates]),
                    "usage": usage,
                    "coverage_sufficient": sufficient,
                    "coverage_message": message,
                },
                "parsed": {
                    "retrieval_text": prior["analysis"]["retrieval_text"],
                    "candidates": parsed_candidates,
                    "metrics": score_case(case, [item["id"] for item in parsed_candidates]),
                },
            }
            record["results"].append(pair)
            record["summary"] = summarize_pairs(cases, record["results"])
            save_run(output, record)
            print(f"已保存：{case['id']} ({len(record['results'])}/{len(cases)})", flush=True)
        except (QuestionLocatorError, ValueError, KeyError, TypeError) as error:
            record["status"] = "interrupted"
            record["error"] = {"case_id": case["id"], "type": type(error).__name__}
            save_run(output, record)
            raise RuntimeError(f"{case['id']} 对比中断；已完成结果保存在 {output}") from error
    record["status"] = "completed"
    save_run(output, record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "test"), help="新运行选择调整题或测试题")
    parser.add_argument("--prior-run", type=Path, help="此前同组的真实 LLM 评测结果 JSON")
    parser.add_argument("--resume", type=Path, help="从未完成的对比结果文件续跑")
    parser.add_argument("--yes", action="store_true", help="确认本组题目的付费嵌入调用")
    args = parser.parse_args()
    if args.resume:
        if args.split or args.prior_run:
            parser.error("--resume 不需要再指定 --split 或 --prior-run")
        output = project_path(args.resume)
        try:
            record = read_json(output)
            split = record["split"]
            prior_path = project_path(record["prior_run"])
        except (KeyError, TypeError, ValueError) as error:
            parser.error(str(error))
    else:
        if not args.split or not args.prior_run:
            parser.error("新运行必须指定 --split 和 --prior-run")
        record = None
        split = args.split
        prior_path = project_path(args.prior_run)
    if not args.yes:
        parser.error("原文检索会调用付费嵌入 API；确认后增加 --yes")

    try:
        all_cases = load_cases(DATASET)
        validate_cases(all_cases)
        cases = select_cases(all_cases, split)
        prior = read_json(prior_path)
        settings = load_ai_settings(require_key=True)
        index = load_index(settings)
        dataset_sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
        prior_sha = hashlib.sha256(prior_path.read_bytes()).hexdigest()
        index_sha = hashlib.sha256(INDEX_FILE.read_bytes()).hexdigest()
        validate_prior_run(prior, cases, dataset_sha, index, INDEX_FILE.stat().st_mtime)
        if record is not None:
            check_resume(record, split, prior_sha, dataset_sha, index_sha, cases)
    except (OSError, ValueError, KeyError, TypeError, QuestionLocatorError) as error:
        parser.error(str(error))

    if record is None:
        output = new_run_path(DATASET, f"comparison_{split}")
        record = {
            "status": "created",
            "mode": "raw_vs_parsed",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "split": split,
            "dataset": str(DATASET.relative_to(ROOT)),
            "dataset_sha256": dataset_sha,
            "prior_run": str(prior_path.relative_to(ROOT)),
            "prior_run_sha256": prior_sha,
            "index_sha256": index_sha,
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "query_instruction": QUERY_INSTRUCTION,
            "selected_case_ids": [case["id"] for case in cases],
            "results": [],
            "summary": None,
        }
    remaining = len(cases) - len(record["results"])
    print(f"将调用付费嵌入 API {remaining} 次；不调用 LLM，不重新编码索引节点。", flush=True)
    run_cases(cases, prior["results"], settings, record, output)
    print(json.dumps(record["summary"], ensure_ascii=False, indent=2))
    print(f"对比结果已保存：{output}")


if __name__ == "__main__":
    main()
