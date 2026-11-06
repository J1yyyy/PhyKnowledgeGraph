"""语义关系导入边界的离线测试。"""
import unittest

from materials.import_phykgraph_json import validate_graph


def graph(relation_type, source_type, target_type, verification=None):
    edge = {
        "source_id": "source", "relation_type": relation_type, "target_id": "target",
    }
    if verification is not None:
        edge["verification"] = verification
    return {
        "entities": [
            {"id": "source", "type": source_type, "name": "起点"},
            {"id": "target", "type": target_type, "name": "终点"},
        ],
        "edges": [edge],
    }


class SemanticRelationValidationTests(unittest.TestCase):
    def test_measurement_requires_quantitative_target(self):
        validate_graph(graph("MEASURES", "MEASUREMENT_TOOL", "PHYSICAL_QUANTITY"))
        with self.assertRaisesRegex(ValueError, "关系类型组合不合法"):
            validate_graph(graph("MEASURES", "MEASUREMENT_TOOL", "PHYSICS_CONCEPT"))

    def test_application_direction_and_subtype_pairs(self):
        validate_graph(graph("APPLIED_IN", "PHYSICAL_QUANTITY", "PHYSICS_MODEL"))
        validate_graph(graph("IS_A", "PHYSICS_MODEL", "PHYSICS_CONCEPT"))
        with self.assertRaisesRegex(ValueError, "关系类型组合不合法"):
            validate_graph(graph("APPLIED_IN", "PHYSICS_MODEL", "PHYSICAL_QUANTITY"))
        with self.assertRaisesRegex(ValueError, "IS_A 类型组合不合法"):
            validate_graph(graph("IS_A", "PHYSICS_CONCEPT", "PHYSICS_MODEL"))

    def test_unreviewed_candidate_cannot_be_imported(self):
        with self.assertRaisesRegex(ValueError, "待审核语义关系不能直接导入"):
            validate_graph(graph("IS_A", "PHYSICS_MODEL", "PHYSICS_CONCEPT", "semantic_candidate_needs_review"))


if __name__ == "__main__":
    unittest.main()
