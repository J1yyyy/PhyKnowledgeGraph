"""题目上下文筛选测试；只使用模拟关系，不连接数据库或付费接口。"""
import unittest

from pydantic import ValidationError

from backend.question_context import QuestionContextRequest, select_question_context


def request(candidates=None, concepts=None, retrieval_text="测量密度", coverage=True):
    return QuestionContextRequest.model_validate({
        "candidates": candidates or [
            {"id": "junior_physics:A", "score": 0.8},
            {"id": "junior_physics:B", "score": 0.6},
        ],
        "analysis": {
            "domain": "物理", "task": "求密度", "known_quantities": [],
            "target_quantity": "密度", "candidate_concepts": concepts or ["密度公式"],
            "retrieval_text": retrieval_text,
        },
        "coverage_sufficient": coverage,
    })


def edge(candidate, neighbor, name, relation="RELATED_TO", source=None, target=None):
    return {
        "candidate_id": f"junior_physics:{candidate}",
        "neighbor_id": f"junior_physics:{neighbor}",
        "neighbor_label": name,
        "from": f"junior_physics:{source or candidate}",
        "to": f"junior_physics:{target or neighbor}",
        "relation_type": relation,
        "label": relation,
    }


class QuestionContextTests(unittest.TestCase):
    def test_candidate_ids_scores_and_count_are_validated(self):
        with self.assertRaises(ValidationError):
            request(candidates=[{"id": "other:A", "score": 0.8}])
        with self.assertRaises(ValidationError):
            request(candidates=[{"id": "junior_physics:A", "score": 1.2}])
        with self.assertRaises(ValidationError):
            request(candidates=[{"id": "junior_physics:A"}] * 2)
        with self.assertRaises(ValidationError):
            request(candidates=[{"id": f"junior_physics:{i}"} for i in range(6)])

    def test_all_candidates_and_only_relevant_real_edges(self):
        rows = [
            edge("A", "B", "候选 B", "PREREQUISITE"),
            edge("B", "A", "候选 A", "PREREQUISITE", source="A", target="B"),
            edge("A", "F", "密度公式", "DESCRIBED_BY"),
            edge("A", "U", "无关实体"),
            edge("A", "C", "教材第一章", "TAUGHT_IN"),
        ]
        ids, edges = select_question_context(request(), rows)
        self.assertEqual(ids, ["junior_physics:A", "junior_physics:B", "junior_physics:F"])
        self.assertEqual({item["relation_type"] for item in edges}, {"PREREQUISITE", "DESCRIBED_BY"})
        self.assertEqual(len(edges), 2)

    def test_shared_support_is_allowed_and_count_capped(self):
        rows = [edge("A", "S", "共同知识"), edge("B", "S", "共同知识")]
        rows += [edge("A", f"F{i}", "密度公式") for i in range(12)]
        ids, edges = select_question_context(request(), rows)
        self.assertIn("junior_physics:S", ids)
        self.assertEqual(len(ids), 10)  # 2 个候选 + 最多 8 个支持节点
        self.assertTrue(all(item["from"] in ids and item["to"] in ids for item in edges))

    def test_insufficient_coverage_does_not_expand_neighbors(self):
        rows = [edge("A", "B", "候选 B"), edge("A", "F", "密度公式")]
        ids, edges = select_question_context(request(coverage=False), rows)
        self.assertEqual(ids, ["junior_physics:A", "junior_physics:B"])
        self.assertEqual(len(edges), 1)

    def test_reviewed_subtype_and_measurement_relations_can_support_context(self):
        rows = [
            edge("A", "M", "测量密度", "MEASURES"),
            edge("B", "K", "密度公式", "IS_A"),
        ]
        ids, edges = select_question_context(request(concepts=["测量密度", "密度公式"]), rows)
        self.assertEqual(ids, ["junior_physics:A", "junior_physics:B", "junior_physics:M", "junior_physics:K"])
        self.assertEqual({item["relation_type"] for item in edges}, {"MEASURES", "IS_A"})


if __name__ == "__main__":
    unittest.main()
