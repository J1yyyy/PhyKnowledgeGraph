"""用人工标注题目评测候选 Top-5；默认离线，不产生 API 费用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "question_eval.json"


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    parser.add_argument("--live", action="store_true", help="调用真实 LLM 和嵌入 API；7 道题各调用一次")
    parser.add_argument("--yes", action="store_true", help="确认执行实时付费评测")
    args = parser.parse_args()
    if args.live and not args.yes:
        parser.error("实时评测会调用 7 次 LLM 和 7 次嵌入 API；确认后请增加 --yes")

    examples = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    hits = 0
    covered_count = 0
    uncovered_ok = 0
    failures = []
    mode = "live_api" if args.live else "offline_example"

    for example in examples:
        result = request_json(args.base_url, "POST", "/api/junior_physics/question/locate", {
            "question": example["question"],
            "mode": mode,
            "example_id": example["id"] if not args.live else None,
        })
        assert len(result["candidates"]) <= 5
        actual_ids = [item["id"] for item in result["candidates"]]
        for candidate_id in actual_ids:
            detail = request_json(
                args.base_url,
                "GET",
                "/api/junior_physics/node/" + quote(candidate_id, safe=""),
            )
            assert detail["n"]["id"] == candidate_id

        expected_ids = set(example["expected_entity_ids"])
        if example["coverage_expected"]:
            covered_count += 1
            hit = bool(expected_ids & set(actual_ids))
            hits += int(hit)
            if not hit:
                failures.append({
                    "id": example["id"],
                    "question": example["question"],
                    "expected": sorted(expected_ids),
                    "actual": actual_ids,
                })
        else:
            if result["coverage_sufficient"] is False:
                uncovered_ok += 1
            else:
                failures.append({
                    "id": example["id"],
                    "question": example["question"],
                    "expected": "图谱覆盖不足",
                    "actual": result["coverage_sufficient"],
                })

    print(f"运行模式：{'实时 API' if args.live else '离线示例（不代表实时检索效果）'}")
    print(f"有覆盖题目 Top-5 命中：{hits}/{covered_count}")
    print(f"未覆盖题目识别：{uncovered_ok}/{sum(not item['coverage_expected'] for item in examples)}")
    if failures:
        print("失败案例：")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    else:
        print("失败案例：无")
    print("PASS：所有返回候选 ID 均可在 Neo4j 中查询")


if __name__ == "__main__":
    main()
