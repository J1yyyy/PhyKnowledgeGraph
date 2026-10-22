"""题目定位模块的离线单元测试；不连接 Neo4j，不调用外部 API。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from backend import question_locator as locator
from materials import build_local_index as index_builder


class QuestionLocatorTests(unittest.TestCase):
    def settings(self, model="embedding-test"):
        return locator.AISettings(
            base_url="https://example.invalid",
            api_key="test-only",
            llm_model="llm-test",
            embedding_model=model,
            embedding_dimensions=3,
            timeout_seconds=1,
            coverage_threshold=0.5,
        )

    def test_empty_question_is_rejected(self):
        with self.assertRaises(ValidationError):
            locator.LocateQuestionRequest(question="   ")

    def test_offline_example_is_explicit(self):
        example = locator.load_examples()[0]
        result = locator.locate_offline_example(locator.LocateQuestionRequest(
            question=example["question"], mode="offline_example", example_id=example["id"]
        ))
        self.assertEqual(result["source"], "offline_example")
        self.assertEqual(result["retrieval_status"], "not_run")
        self.assertIsNone(result["candidates"][0]["score"])

    def test_cosine_ranking_and_metadata_mismatch(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.npz"
            settings = self.settings()
            metadata = {
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": 3,
                "source_fingerprint": locator.source_fingerprint(),
                "text_format_version": locator.TEXT_FORMAT_VERSION,
                "index_filter_version": locator.INDEX_FILTER_VERSION,
                "corpus_instruction": locator.CORPUS_INSTRUCTION,
                "query_instruction": locator.QUERY_INSTRUCTION,
            }
            np.savez_compressed(
                path,
                ids=np.asarray(["junior_physics:A", "junior_physics:B"]),
                source_ids=np.asarray(["A", "B"]),
                names=np.asarray(["甲", "乙"]),
                types=np.asarray(["PHYSICS_CONCEPT", "PHYSICS_CONCEPT"]),
                texts=np.asarray(["甲", "乙"]),
                vectors=np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float32),
                metadata=np.asarray(json.dumps(metadata)),
            )
            locator._index_cache.path = None
            locator._index_cache.data = None
            with patch.object(locator, "INDEX_FILE", path):
                candidates, sufficient, _ = locator.search_index(
                    np.asarray([0.9, 0.1, 0], dtype=np.float32), settings
                )
                self.assertEqual(candidates[0]["id"], "junior_physics:A")
                self.assertTrue(sufficient)
                locator._index_cache.path = None
                locator._index_cache.data = None
                with self.assertRaises(locator.QuestionLocatorError) as caught:
                    locator.load_index(self.settings(model="other-model"))
                self.assertEqual(caught.exception.code, "INDEX_MISMATCH")

    def test_invalid_llm_output_is_rejected(self):
        with patch.object(locator, "_post_json", return_value={"choices": [{"message": {"content": "not json"}}]}):
            with self.assertRaises(locator.QuestionLocatorError) as caught:
                locator.parse_question("测试题", self.settings())
        self.assertEqual(caught.exception.code, "LLM_OUTPUT_INVALID")

    def test_index_build_checkpoint_can_resume(self):
        entities = [
            {"id": "A", "name": "甲", "type": "PHYSICS_CONCEPT"},
            {"id": "B", "name": "乙", "type": "PHYSICS_CONCEPT"},
        ]
        metadata = index_builder.index_metadata(self.settings(), len(entities))
        vectors = [np.asarray([1, 0, 0], dtype=np.float32)]
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "partial.npz"
            with patch.object(index_builder, "PARTIAL_INDEX_FILE", checkpoint):
                index_builder.save_index(checkpoint, entities[:1], vectors, metadata)
                loaded = index_builder.load_checkpoint(entities, metadata)
        self.assertEqual(len(loaded), 1)
        np.testing.assert_array_equal(loaded[0], vectors[0])

    def test_catalog_nodes_are_not_search_candidates(self):
        entities = json.loads(locator.SOURCE_FILE.read_text(encoding="utf-8"))["entities"]
        searchable = [entity for entity in entities if locator.is_searchable_entity(entity)]
        self.assertEqual((len(entities), len(searchable)), (436, 319))
        self.assertFalse(any(entity["type"] in locator.CATALOG_TYPES for entity in searchable))

    def test_legacy_vectors_reused_only_for_matching_text(self):
        entities = [
            {"id": "G_NODE_5", "name": "密度", "type": "PHYSICAL_QUANTITY"},
            {"id": "RJ24_K_NEW", "name": "新知识", "type": "PHYSICS_CONCEPT"},
        ]
        settings = self.settings()
        metadata = {
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "text_format_version": locator.TEXT_FORMAT_VERSION,
            "corpus_instruction": locator.CORPUS_INSTRUCTION,
            "query_instruction": locator.QUERY_INSTRUCTION,
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.npz"
            np.savez_compressed(
                path,
                source_ids=np.asarray(["G_NODE_5", "RJ24_K_NEW"]),
                texts=np.asarray([locator.entity_text(entities[0]), "不匹配的知识文本"]),
                vectors=np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float32),
                metadata=np.asarray(json.dumps(metadata)),
            )
            with patch.object(index_builder, "LEGACY_INDEX_FILE", path):
                reusable = index_builder.load_reusable_vectors(entities, settings)
        self.assertEqual(set(reusable), {"G_NODE_5"})

    def test_missing_index_rejected_before_paid_request(self):
        with TemporaryDirectory() as directory:
            with patch.object(locator, "INDEX_FILE", Path(directory) / "missing.npz"):
                with patch.object(locator, "load_ai_settings", return_value=self.settings()):
                    with patch.object(locator, "_post_json") as post:
                        with self.assertRaises(locator.QuestionLocatorError) as caught:
                            locator.locate_live("测试题")
        self.assertEqual(caught.exception.code, "INDEX_MISSING")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
