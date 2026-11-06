"""题集校验、指标和结果保存的离线测试。"""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from materials import compare_question_retrieval as comparison
from materials import evaluate_question_locator as evaluator


DATASET = evaluator.ROOT / "data" / "question_eval_50.json"


class QuestionEvaluationTests(unittest.TestCase):
    def test_fifty_cases_and_confirmed_label_changes(self):
        cases = evaluator.load_cases(DATASET)
        audit = evaluator.validate_cases(cases)
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(audit["total"], 50)
        self.assertEqual(audit["coverage_counts"], {
            "covered": 46, "outside_core": 3, "partially_outside": 1,
        })
        self.assertEqual(audit["split_counts"], {"development": 10, "test": 40})
        self.assertEqual(audit["source_page_matched"], 33)
        self.assertEqual(audit["source_user_confirmed"], 17)
        self.assertEqual(audit["source_not_verified"], 0)
        self.assertEqual(len(evaluator.select_cases(cases, "development")), 10)
        self.assertEqual(len(evaluator.select_cases(cases, "test")), 40)
        self.assertEqual(by_id["T09"]["coverage"], "covered")
        self.assertEqual(by_id["T10"]["coverage"], "partially_outside")
        self.assertIn("junior_physics:RJ24_K_015", evaluator.expected_ids(by_id["T22"]))
        self.assertIn("junior_physics:G_NODE_87", evaluator.expected_ids(by_id["T23"]))
        self.assertIn("junior_physics:RJ24_K_047", evaluator.expected_ids(by_id["T23"]))
        self.assertIn("junior_physics:G_NODE_67", evaluator.expected_ids(by_id["T44"]))
        # 用户要求 T30、T46 保留原核心标注。
        self.assertIn("junior_physics:RJ24_K_182", evaluator.expected_ids(by_id["T30"]))
        self.assertIn("junior_physics:G_NODE_74", evaluator.expected_ids(by_id["T46"]))

    def test_legacy_examples_still_validate(self):
        cases = evaluator.load_cases(evaluator.EVAL_FILE)
        self.assertEqual(evaluator.validate_cases(cases)["total"], 7)

    def test_hit_and_recall_only_score_covered_cases(self):
        case = {
            "id": "T",
            "question": "测试",
            "coverage": "covered",
            "core_nodes": [
                {"id": "junior_physics:A"},
                {"id": "junior_physics:B"},
            ],
        }
        metrics = evaluator.score_case(case, ["junior_physics:X", "junior_physics:B"])
        self.assertFalse(metrics["hit_at_1"])
        self.assertTrue(metrics["hit_at_5"])
        self.assertEqual(metrics["recall_at_5"], 0.5)
        case["coverage"] = "partially_outside"
        partial = evaluator.score_case(case, ["junior_physics:B"])
        self.assertIsNone(partial["hit_at_5"])
        self.assertIsNone(partial["recall_at_5"])

    def test_saved_runs_do_not_overwrite_each_other(self):
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            first = evaluator.new_run_path(DATASET, "live_api", run_dir)
            evaluator.save_run(first, {"status": "completed", "results": [{"id": "T01"}]})
            second = evaluator.new_run_path(DATASET, "live_api", run_dir)
            evaluator.save_run(second, {"status": "completed", "results": []})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["results"][0]["id"], "T01")
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["results"], [])

    def test_validate_only_does_not_create_a_run_file(self):
        with patch("sys.argv", ["evaluate_question_locator.py", "--dataset", str(DATASET), "--validate-only"]):
            with patch.object(evaluator, "new_run_path", side_effect=AssertionError("不应创建结果文件")):
                with redirect_stdout(StringIO()) as output:
                    evaluator.main()
        self.assertIn('"source_not_verified": 0', output.getvalue())

    def test_development_and_test_metrics_are_separate(self):
        cases = evaluator.load_cases(DATASET)
        selected = [next(case for case in cases if case["id"] == case_id) for case_id in ("T01", "T02")]
        results = [
            {"id": case["id"], "metrics": evaluator.score_case(case, [evaluator.expected_ids(case)[0]])}
            for case in selected
        ]
        summary = evaluator.summarize(cases, results)
        self.assertEqual(summary["by_split"]["development"]["evaluated"], 1)
        self.assertEqual(summary["by_split"]["test"]["evaluated"], 1)
        self.assertEqual(summary["by_split"]["test"]["hit_at_5"], 1.0)

    def test_unconfigured_coverage_threshold_is_not_counted_as_a_miss(self):
        case = next(case for case in evaluator.load_cases(DATASET) if case["coverage"] == "outside_core")
        result = {
            "id": case["id"], "coverage_sufficient": None,
            "metrics": evaluator.score_case(case, ["junior_physics:G_NODE_5"]),
        }
        summary = evaluator.summarize([case], [result])
        self.assertEqual(summary["outside_core_evaluated"], 1)
        self.assertEqual(summary["outside_core_decided"], 0)
        self.assertIsNone(summary["outside_core_flagged"])

    def test_invalid_graph_id_is_rejected(self):
        case = evaluator.load_cases(DATASET)[0].copy()
        case["core_nodes"] = [{"id": "junior_physics:DOES_NOT_EXIST", "name": "错误"}]
        with self.assertRaisesRegex(ValueError, "知识实体不存在"):
            evaluator.validate_cases([case])

    def test_interrupted_run_preserves_completed_result(self):
        cases = evaluator.load_cases(DATASET)[:2]
        record = {
            "status": "created", "mode": "live_api", "dataset_sha256": "test-hash",
            "selected_case_ids": [case["id"] for case in cases], "results": [], "summary": None,
        }
        candidate_id = evaluator.expected_ids(cases[0])[0]

        def fake_request(_base_url, method, _path, payload=None):
            if method == "POST" and payload["question"] == cases[1]["question"]:
                raise URLError("offline test")
            if method == "POST":
                self.assertEqual(set(payload), {"question", "mode", "example_id"})
                return {
                    "analysis": {"retrieval_text": "离线测试"},
                    "candidates": [{"id": candidate_id, "score": 0.5}],
                    "coverage_sufficient": True,
                }
            return {"n": {"id": candidate_id}}

        with TemporaryDirectory() as directory:
            output = Path(directory) / "run.json"
            with patch.object(evaluator, "request_json", side_effect=fake_request):
                with self.assertRaisesRegex(RuntimeError, "T02 评测中断"):
                    evaluator.evaluate_cases(cases, "http://localhost", "live_api", record, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "interrupted")
            self.assertEqual([item["id"] for item in saved["results"]], ["T01"])
            self.assertEqual(saved["error"]["case_id"], "T02")

            evaluator.check_resume(saved, "test-hash", cases)
            with self.assertRaisesRegex(ValueError, "题集内容或分组已变化"):
                evaluator.check_resume(saved, "changed-hash", cases)

            def resumed_request(_base_url, method, _path, payload=None):
                if method == "POST":
                    self.assertEqual(payload["question"], cases[1]["question"])
                    return {
                        "analysis": {"retrieval_text": "离线测试"},
                        "candidates": [{"id": candidate_id, "score": 0.5}],
                        "coverage_sufficient": True,
                    }
                return {"n": {"id": candidate_id}}

            with patch.object(evaluator, "request_json", side_effect=resumed_request):
                evaluator.evaluate_cases(cases, "http://localhost", "live_api", saved, output)
            completed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(completed["status"], "completed")
            self.assertEqual([item["id"] for item in completed["results"]], ["T01", "T02"])

    def test_comparison_requires_same_dataset_and_index(self):
        case = evaluator.load_cases(DATASET)[0]
        entity_id = evaluator.expected_ids(case)[0]
        index = {
            "metadata_dict": {
                "embedding_model": "model", "embedding_dimensions": 1024,
                "source_fingerprint": "graph-sha",
            },
            "ids": [entity_id],
        }
        prior = {
            "status": "completed", "mode": "live_api", "dataset_sha256": "dataset-sha",
            "selected_case_ids": [case["id"]], "created_at_utc": "2026-10-25T15:40:44+00:00",
            "results": [{
                "id": case["id"],
                "index": {"embedding_model": "model", "dimension": 1024, "source_fingerprint": "graph-sha"},
                "analysis": {"retrieval_text": "密度"},
                "candidates": [{"id": entity_id}],
            }],
        }
        comparison.validate_prior_run(prior, [case], "dataset-sha", index, 0)
        with self.assertRaisesRegex(ValueError, "题集或题目顺序不匹配"):
            comparison.validate_prior_run(prior, [case], "changed", index, 0)
        with self.assertRaisesRegex(ValueError, "当前索引晚于旧 LLM 结果"):
            comparison.validate_prior_run(prior, [case], "dataset-sha", index, 9999999999)

    def test_comparison_pairs_and_resume_only_call_missing_question(self):
        cases = evaluator.load_cases(DATASET)[:2]
        first_id = evaluator.expected_ids(cases[0])[0]
        second_id = evaluator.expected_ids(cases[1])[0]
        first_pair = {
            "id": cases[0]["id"],
            "raw": {"metrics": evaluator.score_case(cases[0], [])},
            "parsed": {"metrics": evaluator.score_case(cases[0], [first_id])},
        }
        prior_rows = [
            {"analysis": {"retrieval_text": "旧解析"}, "candidates": [{"id": first_id}]},
            {"analysis": {"retrieval_text": "旧解析"}, "candidates": [{"id": "junior_physics:G_NODE_5"}]},
        ]
        record = {"status": "interrupted", "results": [first_pair], "summary": None}
        with TemporaryDirectory() as directory:
            output = Path(directory) / "comparison.json"
            with patch.object(comparison, "embed_text", return_value=(object(), {"total_tokens": 5})) as embedded:
                with patch.object(comparison, "search_index", return_value=([{"id": second_id}], None, None)):
                    comparison.run_cases(cases, prior_rows, object(), record, output)
            embedded.assert_called_once()
            self.assertEqual(embedded.call_args.args[0], cases[1]["question"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")
            self.assertEqual([row["id"] for row in saved["results"]], [cases[0]["id"], cases[1]["id"]])
            self.assertEqual(saved["summary"]["hit_at_5_pairs"]["parsed_better"], [cases[0]["id"]])
            self.assertEqual(saved["summary"]["hit_at_5_pairs"]["raw_better"], [cases[1]["id"]])


if __name__ == "__main__":
    unittest.main()
