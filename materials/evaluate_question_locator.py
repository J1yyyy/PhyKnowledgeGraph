"""校验人工题集并评测题目定位；每次运行都保存结果。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "question_eval.json"
SOURCE_FILE = ROOT / "data" / "junior_physics_2024.json"
RUN_DIR = ROOT / "data" / "generated" / "question_eval_runs"
PROJECT_ID = "junior_physics"
CATALOG_TYPES = {"TEXTBOOK_VOLUME", "CHAPTER", "SECTION"}
COVERAGE_TYPES = {"covered", "partially_outside", "outside_core"}


def request_json(base_url: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def load_cases(path: Path) -> list[dict]:
    """保留七道离线示例格式，新增五十题独立题集。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"评测文件无法读取或不是合法 JSON：{path}") from error
    if isinstance(data, dict):
        if data.get("schema_version") != 1 or data.get("project_id") != PROJECT_ID:
            raise ValueError("题集版本或项目 ID 不匹配")
        cases = data.get("cases")
    else:
        cases = data
    if not isinstance(cases, list) or not cases:
        raise ValueError("题集必须包含非空数组")
    return cases


def coverage_of(case: dict) -> str:
    if "coverage" in case:
        return case["coverage"]
    return "covered" if case["coverage_expected"] else "outside_core"


def expected_ids(case: dict) -> list[str]:
    if "core_nodes" in case:
        return [item["id"] for item in case["core_nodes"]]
    return list(case["expected_entity_ids"])


def validate_cases(cases: list[dict]) -> dict:
    """仅用图谱 JSON 检查题目与实体映射，不连接 Neo4j。"""
    entities = json.loads(SOURCE_FILE.read_text(encoding="utf-8-sig"))["entities"]
    by_id = {f"{PROJECT_ID}:{item['id']}": item for item in entities}
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    coverage_counts = {name: 0 for name in sorted(COVERAGE_TYPES)}
    split_counts: dict[str, int] = {}
    matched_sources = 0
    user_confirmed_sources = 0
    mismatched_sources = 0
    for case in cases:
        case_id = case.get("id")
        question = case.get("question")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise ValueError(f"题目 ID 缺失或重复：{case_id}")
        if not isinstance(question, str) or not question.strip() or question in seen_questions:
            raise ValueError(f"{case_id}：题目为空或重复")
        seen_ids.add(case_id)
        seen_questions.add(question)
        coverage = coverage_of(case)
        if coverage not in COVERAGE_TYPES:
            raise ValueError(f"{case_id}：未知覆盖类型 {coverage}")
        coverage_counts[coverage] += 1
        core_ids = expected_ids(case)
        if coverage == "covered" and not core_ids:
            raise ValueError(f"{case_id}：已覆盖题必须标出核心知识点")
        if coverage == "outside_core" and core_ids:
            raise ValueError(f"{case_id}：核心未覆盖题不能有核心知识点 ID")
        marked = case.get("core_nodes", []) + case.get("supporting_nodes", [])
        if len({item["id"] for item in marked}) != len(marked):
            raise ValueError(f"{case_id}：核心和辅助知识点重复")
        for entity_id in core_ids:
            if not isinstance(entity_id, str) or not entity_id.startswith(f"{PROJECT_ID}:"):
                raise ValueError(f"{case_id}：实体 ID 缺少 {PROJECT_ID}: 前缀")
        for item in marked or [{"id": entity_id} for entity_id in core_ids]:
            entity_id = item["id"]
            entity = by_id.get(entity_id)
            if entity is None or entity["type"] in CATALOG_TYPES:
                raise ValueError(f"{case_id}：知识实体不存在或误选目录：{entity_id}")
            if "name" in item and item["name"] != entity["name"]:
                raise ValueError(f"{case_id}：实体名称与图谱不一致：{entity_id}")
        if "source_url" in case:
            if not isinstance(case["source_url"], str) or not case["source_url"].startswith("https://"):
                raise ValueError(f"{case_id}：来源链接无效")
            if case.get("source_match") not in {
                "matched_page_question", "user_confirmed", "mismatched_page_question", "not_verified"
            }:
                raise ValueError(f"{case_id}：来源核对状态无效")
            matched_sources += case["source_match"] == "matched_page_question"
            user_confirmed_sources += case["source_match"] == "user_confirmed"
            mismatched_sources += case["source_match"] == "mismatched_page_question"
        if "split" in case:
            split = case["split"]
            if split not in {"development", "test"}:
                raise ValueError(f"{case_id}：未知数据划分 {split}")
            split_counts[split] = split_counts.get(split, 0) + 1
    return {
        "total": len(cases),
        "coverage_counts": coverage_counts,
        "split_counts": split_counts,
        "source_page_matched": matched_sources if "source_url" in cases[0] else None,
        "source_user_confirmed": user_confirmed_sources if "source_url" in cases[0] else None,
        "source_page_mismatched": mismatched_sources if "source_url" in cases[0] else None,
        "source_not_verified": len(cases) - matched_sources - user_confirmed_sources - mismatched_sources if "source_url" in cases[0] else None,
        "json_id_and_name_check": "passed",
        "neo4j_id_check": "not_run",
    }


def score_case(case: dict, candidate_ids: list[str]) -> dict:
    """部分覆盖和未覆盖题不混入完整覆盖题的检索指标。"""
    core = set(expected_ids(case))
    top5 = candidate_ids[:5]
    matched = core.intersection(top5)
    covered = coverage_of(case) == "covered"
    return {
        "core_ids": sorted(core),
        "candidate_ids": top5,
        "matched_core_ids": sorted(matched),
        "hit_at_1": bool(top5 and top5[0] in core) if covered else None,
        "hit_at_5": bool(matched) if covered else None,
        "recall_at_5": len(matched) / len(core) if covered else None,
    }


def summarize(cases: list[dict], results: list[dict]) -> dict:
    by_id = {case["id"]: case for case in cases}

    def retrieval_summary(rows: list[dict]) -> dict:
        eligible = [item for item in rows if coverage_of(by_id[item["id"]]) == "covered"]
        outside = [item for item in rows if coverage_of(by_id[item["id"]]) == "outside_core"]
        decided = [item for item in outside if item["coverage_sufficient"] is not None]
        count = len(eligible)
        return {
            "evaluated": len(rows),
            "covered_evaluated": count,
            "hit_at_1": sum(item["metrics"]["hit_at_1"] for item in eligible) / count if count else None,
            "hit_at_5": sum(item["metrics"]["hit_at_5"] for item in eligible) / count if count else None,
            "recall_at_5": sum(item["metrics"]["recall_at_5"] for item in eligible) / count if count else None,
            "failed_case_ids": [item["id"] for item in eligible if not item["metrics"]["hit_at_5"]],
            "outside_core_evaluated": len(outside),
            "outside_core_decided": len(decided),
            "outside_core_flagged": sum(item["coverage_sufficient"] is False for item in decided) if decided else None,
        }

    summary = retrieval_summary(results)
    if any("split" in case for case in cases):
        # 开发题可用于调参，最终效果需单独查看未参与调参的测试题。
        summary["by_split"] = {
            split: retrieval_summary([item for item in results if by_id[item["id"]]["split"] == split])
            for split in ("development", "test")
        }
    return summary


def new_run_path(dataset: Path, mode: str, run_dir: Path = RUN_DIR) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return run_dir / f"{stamp}_{dataset.stem}_{mode}_{uuid4().hex[:8]}.json"


def save_run(path: Path, record: dict) -> None:
    """逐题原子保存；失败时保留已完成结果，且不覆盖旧运行。"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def select_cases(cases: list[dict], split: str | None) -> list[dict]:
    selected = [case for case in cases if split is None or case.get("split") == split]
    if not selected:
        raise ValueError(f"题集中没有 {split} 题目")
    return selected


def check_resume(record: dict, dataset_sha256: str, selected: list[dict]) -> None:
    """先核对题集指纹和题目顺序，避免续跑时把新结果混入旧指标。"""
    selected_ids = [case["id"] for case in selected]
    completed_ids = [item["id"] for item in record["results"]]
    if record.get("mode") != "live_api" or record.get("status") == "completed":
        raise ValueError("只能续跑尚未完成的实时评测")
    if record.get("dataset_sha256") != dataset_sha256 or record.get("selected_case_ids") != selected_ids:
        raise ValueError("题集内容或分组已变化，不能与旧结果合并")
    if completed_ids != selected_ids[:len(completed_ids)]:
        raise ValueError("已完成题目与当前题集顺序不一致")


def evaluate_cases(cases: list[dict], base_url: str, mode: str, record: dict, output: Path) -> None:
    completed = len(record["results"])
    record["status"] = "running"
    record.pop("error", None)
    save_run(output, record)
    for case in cases[completed:]:
        try:
            result = request_json(base_url, "POST", f"/api/{PROJECT_ID}/question/locate", {
                "question": case["question"],
                "mode": mode,
                "example_id": case["id"] if mode == "offline_example" else None,
            })
            candidates = result["candidates"]
            if len(candidates) > 5:
                raise ValueError("接口返回超过 5 个候选")
            candidate_ids = [item["id"] for item in candidates]
            for entity_id in candidate_ids:
                detail = request_json(base_url, "GET", f"/api/{PROJECT_ID}/node/" + quote(entity_id, safe=""))
                if detail["n"]["id"] != entity_id:
                    raise ValueError(f"详情接口 ID 不一致：{entity_id}")
            record["results"].append({
                "id": case["id"],
                "coverage": coverage_of(case),
                "analysis": result["analysis"],
                "candidates": candidates,
                "coverage_sufficient": result["coverage_sufficient"],
                "coverage_message": result.get("coverage_message"),
                "index": result.get("index"),
                "usage": result.get("usage"),
                "metrics": score_case(case, candidate_ids),
            })
            record["summary"] = summarize(cases, record["results"])
            save_run(output, record)
            print(f"已保存：{case['id']} ({len(record['results'])}/{len(cases)})")
        except (HTTPError, URLError, ValueError, KeyError) as error:
            record["status"] = "interrupted"
            record["error"] = {"case_id": case["id"], "type": type(error).__name__}
            save_run(output, record)
            raise RuntimeError(f"{case['id']} 评测中断；已完成结果保存在 {output}") from error
    record["status"] = "completed"
    save_run(output, record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=EVAL_FILE)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    parser.add_argument("--validate-only", action="store_true", help="仅校验题集与图谱 JSON，不调用 API")
    parser.add_argument("--live", action="store_true", help="调用真实 LLM 与查询嵌入 API")
    parser.add_argument("--split", choices=("development", "test"), help="五十题实时评测按开发集或测试集运行")
    parser.add_argument("--resume", type=Path, help="续跑未完成的实时评测结果文件")
    parser.add_argument("--yes", action="store_true", help="确认本次实时评测的付费调用")
    args = parser.parse_args()
    resume_file = None
    record = None
    if args.resume:
        if args.validate_only or args.live or args.split or args.dataset != EVAL_FILE:
            parser.error("--resume 只需搭配 --yes，题集和分组从结果文件读取")
        resume_file = args.resume if args.resume.is_absolute() else ROOT / args.resume
        try:
            record = json.loads(resume_file.read_text(encoding="utf-8"))
            dataset = ROOT / record["dataset"]
            split = record["split"]
            base_url = record["base_url"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            parser.error(f"续跑文件无法读取或缺少必要字段：{error}")
        if not args.yes:
            parser.error("续跑会继续调用付费 API；确认后增加 --yes")
    else:
        dataset = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
        split = args.split
        base_url = args.base_url
    try:
        cases = load_cases(dataset)
        audit = validate_cases(cases)
        selected = select_cases(cases, split)
        dataset_sha256 = hashlib.sha256(dataset.read_bytes()).hexdigest()
        if record is not None:
            check_resume(record, dataset_sha256, selected)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    if args.validate_only and args.live:
        parser.error("--validate-only 与 --live 不能同时使用")
    live = args.live or record is not None
    if live and not args.yes:
        parser.error(f"实时评测预计调用 {len(selected)} 次 LLM 和 {len(selected)} 次查询嵌入 API；确认付费后增加 --yes")
    if live and any("split" in case for case in cases) and split is None:
        parser.error("五十题实时评测必须指定 --split development 或 --split test")
    if not args.validate_only and not live and dataset != EVAL_FILE:
        parser.error("五十题请先用 --validate-only；实时评测需另用 --live --yes")

    if args.validate_only:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return

    mode = "live_api" if live else "offline_example"
    output = resume_file or new_run_path(dataset, mode)
    if record is None:
        record = {
            "status": "created",
            "mode": mode,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset": str(dataset.relative_to(ROOT)) if dataset.is_relative_to(ROOT) else dataset.name,
            "dataset_sha256": dataset_sha256,
            "split": split,
            "base_url": base_url,
            "selected_case_ids": [case["id"] for case in selected],
            "audit": audit,
            "results": [],
            "summary": None,
        }
    if live:
        remaining = len(selected) - len(record["results"])
        print(f"本次还需调用 {remaining} 次 LLM 和 {remaining} 次查询嵌入 API。")
    evaluate_cases(selected, base_url, mode, record, output)
    print(json.dumps(record["summary"], ensure_ascii=False, indent=2))
    print(f"评测结果已保存：{output}")


if __name__ == "__main__":
    main()
