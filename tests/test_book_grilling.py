from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "book_grilling.py"
SPEC = importlib.util.spec_from_file_location("book_grilling", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class BookGrillingRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.course = self.root / "course"
        self.source = self.root / "work.txt"
        self.source.write_text(
            "示例作品\n\n"
            "第一单元解释甲。甲依赖一个必要条件。\n\n"
            "第二单元解释乙。乙限定了甲的适用范围。\n",
            encoding="utf-8",
        )
        self.unit_one_text = "第一单元解释甲。甲依赖一个必要条件。"
        self.unit_two_text = "第二单元解释乙。乙限定了甲的适用范围。"
        self.unit_one = self.root / "unit-one.txt"
        self.unit_two = self.root / "unit-two.txt"
        self.unit_one.write_text(self.unit_one_text, encoding="utf-8")
        self.unit_two.write_text(self.unit_two_text, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_json(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def run_cli(self, *arguments: object, ok: bool = True) -> dict | str:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            text=True,
            capture_output=True,
            check=False,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 2, result.stdout)
        return result.stderr

    def manifest(
        self,
        *,
        source_units: list[dict] | None = None,
        coverage_scope: str = "complete",
        coverage_note: str = "",
    ) -> dict:
        return {
            "schema_version": 1,
            "book": {
                "id": "example-work",
                "title": "示例作品",
                "author": "示例作者",
                "edition": "测试版，2026",
                "language": "zh-CN",
            },
            "source": {
                "path": str(self.source),
                "kind": "plain-text",
                "coverage_scope": coverage_scope,
                "coverage_note": coverage_note,
            },
            "safe_context": {
                "source_token_limit": 8000,
                "method": "测试用保守上限",
            },
            "source_units": source_units
            or [
                {
                    "id": "part-one",
                    "parent_id": "",
                    "position": 1,
                    "kind": "部分",
                    "title": "第一部分",
                    "locator": "目录：第一部分",
                    "learning_unit": False,
                },
                {
                    "id": "unit-one",
                    "parent_id": "part-one",
                    "position": 1,
                    "kind": "章",
                    "title": "第一单元",
                    "locator": "第一段",
                    "learning_unit": True,
                    "sequence": 1,
                    "split_origin": "author",
                    "estimated_tokens": 30,
                },
                {
                    "id": "unit-two",
                    "parent_id": "part-one",
                    "position": 2,
                    "kind": "章",
                    "title": "第二单元",
                    "locator": "第二段",
                    "learning_unit": True,
                    "sequence": 2,
                    "split_origin": "author",
                    "estimated_tokens": 30,
                },
            ],
        }

    def tree_one(self) -> dict:
        return {
            "schema_version": 1,
            "unit_id": "unit-one",
            "title": "第一单元问题树",
            "source_text_sha256": hashlib.sha256(
                self.unit_one_text.encode("utf-8")
            ).hexdigest(),
            "root_id": "q-root",
            "nodes": [
                {
                    "id": "q-root",
                    "parent_id": "",
                    "position": 1,
                    "question": "第一单元要解释什么？",
                    "recommended_answer": "当前可见答案：它解释甲。",
                    "provenance": "source_explicit",
                    "source": {
                        "locator": "第一单元首句",
                        "excerpt": "第一单元解释甲。",
                    },
                    "interpretive_note": "",
                },
                {
                    "id": "q-condition",
                    "parent_id": "q-root",
                    "position": 1,
                    "question": "甲依赖什么？",
                    "recommended_answer": "LOCKED_SECRET_甲依赖必要条件。",
                    "provenance": "source_explicit",
                    "source": {
                        "locator": "第一单元次句",
                        "excerpt": "甲依赖一个必要条件。",
                    },
                    "interpretive_note": "",
                },
            ],
            "coverage": [
                {
                    "locator": "第一单元全部",
                    "disposition": "knowledge",
                    "node_ids": ["q-root", "q-condition"],
                    "reason": "两句分别说明主题和条件。",
                }
            ],
        }

    def tree_two(self) -> dict:
        return {
            "schema_version": 1,
            "unit_id": "unit-two",
            "title": "第二单元问题树",
            "source_text_sha256": hashlib.sha256(
                self.unit_two_text.encode("utf-8")
            ).hexdigest(),
            "root_id": "q-boundary",
            "nodes": [
                {
                    "id": "q-boundary",
                    "parent_id": "",
                    "position": 1,
                    "question": "第二单元增加了什么？",
                    "recommended_answer": "它用乙限定甲的适用范围。",
                    "provenance": "editorial_synthesis",
                    "source": {
                        "locator": "第二单元全部",
                        "excerpt": "第二单元解释乙。乙限定了甲的适用范围。",
                    },
                    "interpretive_note": "这是对两句关系的整理。",
                }
            ],
            "coverage": [
                {
                    "locator": "第二单元全部",
                    "disposition": "knowledge",
                    "node_ids": ["q-boundary"],
                    "reason": "完整覆盖乙及其限定作用。",
                }
            ],
        }

    @staticmethod
    def review(artifact_type: str, artifact: dict, source_hash: str, unit: str = "") -> dict:
        value = {
            "schema_version": 1,
            "artifact_type": artifact_type,
            "artifact_sha256": RUNTIME.value_sha256(artifact),
            "source_text_sha256": source_hash,
            "verdict": "passed",
            "reviewed_at": "2026-07-29T12:00:00+00:00",
            "reviewer": {
                "independent": True,
                "method": "fresh independent source-to-artifact review",
            },
            "checks": {name: True for name in RUNTIME.REVIEW_CHECKS},
            "issues": [],
        }
        if unit:
            value["unit_id"] = unit
        return value

    def initialize(self, manifest: dict | None = None) -> dict:
        manifest_path = self.write_json("manifest.json", manifest or self.manifest())
        return self.run_cli(
            "init",
            self.course,
            "--manifest",
            manifest_path,
        )

    def prepare(
        self,
        tree: dict,
        source_text_path: Path,
        revision: int,
        unit: str,
    ) -> dict:
        tree_path = self.write_json(f"{unit}-tree.json", tree)
        review = self.review(
            "unit_tree",
            tree,
            tree["source_text_sha256"],
            unit,
        )
        review_path = self.write_json(f"{unit}-review.json", review)
        return self.run_cli(
            "prepare-unit",
            self.course,
            "--tree",
            tree_path,
            "--review",
            review_path,
            "--source-text",
            source_text_path,
            "--expected-revision",
            revision,
            "--expected-unit",
            unit,
        )

    def cache(
        self,
        tree: dict,
        source_text_path: Path,
        unit: str,
    ) -> dict:
        tree_path = self.write_json(f"{unit}-prefetch-tree.json", tree)
        review = self.review(
            "unit_tree",
            tree,
            tree["source_text_sha256"],
            unit,
        )
        review_path = self.write_json(
            f"{unit}-prefetch-review.json",
            review,
        )
        return self.run_cli(
            "cache-unit",
            self.course,
            "--tree",
            tree_path,
            "--review",
            review_path,
            "--source-text",
            source_text_path,
            "--expected-unit",
            unit,
        )

    def commit(
        self,
        *,
        node: str,
        revision: int,
        unit: str,
        outcome: str = "resolved",
        open_question: str = "",
    ) -> dict:
        turn = {"node_id": node, "outcome": outcome}
        if outcome == "open":
            turn["open_question"] = open_question
        else:
            turn.update(
                {
                    "stance": "understood",
                    "learner_note": f"已理解 {node}",
                }
            )
        turn_path = self.write_json("turn.json", turn)
        return self.run_cli(
            "commit",
            self.course,
            "--turn",
            turn_path,
            "--expected-revision",
            revision,
            "--expected-unit",
            unit,
            "--expected-node",
            node,
        )

    def complete_course(self) -> dict:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        context = self.commit(
            node="q-condition",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        context = self.prepare(
            self.tree_two(),
            self.unit_two,
            context["receipt"]["revision"],
            "unit-two",
        )
        context = self.commit(
            node="q-boundary",
            revision=context["receipt"]["revision"],
            unit="unit-two",
        )
        self.assertEqual(context["need"], "prepare_book_synthesis")
        synthesis = {
            "schema_version": 1,
            "question": "这部示例作品总体说明什么？",
            "recommended_answer": "它先解释甲，再由乙限定甲。",
            "unit_contributions": [
                {"unit_id": "unit-one", "contribution": "建立甲及其条件。"},
                {"unit_id": "unit-two", "contribution": "用乙限定甲。"},
            ],
            "boundaries": ["示例文本没有进一步解释必要条件。"],
        }
        synthesis_path = self.write_json("synthesis.json", synthesis)
        review_path = self.write_json(
            "synthesis-review.json",
            self.review(
                "book_synthesis",
                synthesis,
                RUNTIME.file_sha256(self.source),
            ),
        )
        return self.run_cli(
            "finalize",
            self.course,
            "--synthesis",
            synthesis_path,
            "--review",
            review_path,
            "--expected-revision",
            context["receipt"]["revision"],
        )

    def test_full_workflow_is_one_question_at_a_time_and_redacts_locks(self) -> None:
        context = self.initialize()
        self.assertEqual(context["need"], "prepare_current_unit")
        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        self.assertNotIn("LOCKED_SECRET_", page)

        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.assertEqual(context["current_node"]["id"], "q-root")
        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        self.assertIn("当前可见答案", page)
        self.assertIn("甲依赖什么？", page)
        self.assertNotIn("LOCKED_SECRET_", page)

        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
            outcome="open",
            open_question="这里的甲是否只是一个例子？",
        )
        self.assertEqual(context["current_node"]["id"], "q-root")
        self.assertEqual(len(context["open_questions"]), 1)

        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        self.assertEqual(context["current_node"]["id"], "q-condition")
        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        self.assertIn("LOCKED_SECRET_甲依赖必要条件", page)

        before = (self.course / ".book-grilling" / "course.json").read_bytes()
        stale_turn = self.write_json(
            "stale-turn.json",
            {
                "node_id": "q-condition",
                "outcome": "resolved",
                "stance": "understood",
            },
        )
        error = self.run_cli(
            "commit",
            self.course,
            "--turn",
            stale_turn,
            "--expected-revision",
            context["receipt"]["revision"] - 1,
            "--expected-unit",
            "unit-one",
            "--expected-node",
            "q-condition",
            ok=False,
        )
        self.assertIn("Stale revision", error)
        self.assertEqual(
            before,
            (self.course / ".book-grilling" / "course.json").read_bytes(),
        )

        context = self.commit(
            node="q-condition",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        self.assertEqual(context["need"], "prepare_current_unit")
        self.assertEqual(context["receipt"]["current_unit_id"], "unit-two")

        context = self.prepare(
            self.tree_two(),
            self.unit_two,
            context["receipt"]["revision"],
            "unit-two",
        )
        context = self.commit(
            node="q-boundary",
            revision=context["receipt"]["revision"],
            unit="unit-two",
        )
        self.assertEqual(context["need"], "prepare_book_synthesis")

        synthesis = {
            "schema_version": 1,
            "question": "这部示例作品总体说明什么？",
            "recommended_answer": "它先解释甲，再由乙限定甲。",
            "unit_contributions": [
                {"unit_id": "unit-one", "contribution": "建立甲及其条件。"},
                {"unit_id": "unit-two", "contribution": "用乙限定甲。"},
            ],
            "boundaries": ["示例文本没有进一步解释必要条件。"],
        }
        final = self.run_cli(
            "finalize",
            self.course,
            "--synthesis",
            self.write_json("synthesis.json", synthesis),
            "--review",
            self.write_json(
                "synthesis-review.json",
                self.review(
                    "book_synthesis",
                    synthesis,
                    RUNTIME.file_sha256(self.source),
                ),
            ),
            "--expected-revision",
            context["receipt"]["revision"],
        )
        self.assertEqual(final["need"], "complete")
        audit = self.run_cli("audit", self.course)
        self.assertTrue(audit["ok"], audit["errors"])

        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        embedded = page.split(
            '<script id="course-data" type="application/json">', 1
        )[1].split("</script>", 1)[0]
        public = json.loads(embedded)
        self.assertEqual(public["book_status"], "completed")
        self.assertNotIn("artifact_sha256", json.dumps(public))
        self.assertNotIn(str(self.course), json.dumps(public))

    def test_prefetch_auto_activates_at_the_next_unit_boundary(self) -> None:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        state_path = self.course / ".book-grilling" / "course.json"
        page_path = self.course / "book-grilling.html"
        state_before = state_path.read_bytes()
        page_before = page_path.read_bytes()

        background = self.run_cli("prefetch-context", self.course)
        self.assertEqual(background["prefetch"]["unit_id"], "unit-two")
        self.assertEqual(
            background["prefetch"]["need"],
            "prepare_prefetch_unit",
        )
        cached = self.cache(self.tree_two(), self.unit_two, "unit-two")
        self.assertEqual(cached["prefetch"]["status"], "ready")

        # Background preparation is isolated from progress and the reader.
        self.assertEqual(state_before, state_path.read_bytes())
        self.assertEqual(page_before, page_path.read_bytes())

        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        revision_before_boundary = context["receipt"]["revision"]
        context = self.commit(
            node="q-condition",
            revision=revision_before_boundary,
            unit="unit-one",
        )

        self.assertEqual(context["receipt"]["revision"], revision_before_boundary + 1)
        self.assertEqual(context["receipt"]["current_unit_id"], "unit-two")
        self.assertEqual(context["current_node"]["id"], "q-boundary")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            state["unit_records"]["unit-two"]["prepared_via"],
            "prefetch",
        )
        self.assertEqual(
            (self.course / ".book-grilling" / "units" / "unit-two.txt").read_text(
                encoding="utf-8"
            ),
            self.unit_two_text,
        )
        self.assertFalse(
            (
                self.course
                / ".book-grilling"
                / "prefetch"
                / "units"
                / "unit-two"
            ).exists()
        )

    def test_invalid_prefetch_never_blocks_learning_or_unlocks_answers(self) -> None:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.cache(self.tree_two(), self.unit_two, "unit-two")
        cached_text = (
            self.course
            / ".book-grilling"
            / "prefetch"
            / "units"
            / "unit-two"
            / "unit.txt"
        )
        cached_text.write_text("损坏的预制文本", encoding="utf-8")

        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        context = self.commit(
            node="q-condition",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        self.assertEqual(context["need"], "prepare_current_unit")
        self.assertEqual(context["receipt"]["current_unit_id"], "unit-two")
        state = json.loads(
            (self.course / ".book-grilling" / "course.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            state["unit_records"]["unit-two"]["status"],
            "needs_preparation",
        )
        self.assertIsNone(state["unit_records"]["unit-two"]["tree"])
        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        self.assertNotIn("它用乙限定甲的适用范围。", page)
        audit = self.run_cli("audit", self.course)
        self.assertTrue(audit["ok"], audit["errors"])
        self.assertTrue(audit["warnings"])

    def test_prefetch_can_activate_after_a_boundary_race(self) -> None:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        context = self.commit(
            node="q-root",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        context = self.commit(
            node="q-condition",
            revision=context["receipt"]["revision"],
            unit="unit-one",
        )
        self.assertEqual(context["need"], "prepare_current_unit")

        background = self.run_cli("prefetch-context", self.course)
        self.assertEqual(background["prefetch"]["unit_id"], "unit-two")
        self.cache(self.tree_two(), self.unit_two, "unit-two")
        context = self.run_cli("context", self.course)
        self.assertEqual(context["need"], "activate_prefetched_unit")
        context = self.run_cli(
            "activate-prefetched-unit",
            self.course,
            "--expected-revision",
            context["receipt"]["revision"],
            "--expected-unit",
            "unit-two",
        )
        self.assertEqual(context["current_node"]["id"], "q-boundary")
        self.assertEqual(context["prefetch"]["status"], "not_applicable")

    def test_invalidation_archives_affected_prefetch_cache(self) -> None:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.cache(self.tree_two(), self.unit_two, "unit-two")
        cache_dir = (
            self.course
            / ".book-grilling"
            / "prefetch"
            / "units"
            / "unit-two"
        )
        self.assertTrue(cache_dir.is_dir())

        self.run_cli(
            "invalidate-unit",
            self.course,
            "--unit",
            "unit-one",
            "--reason",
            "重新核对第一单元证据",
            "--expected-revision",
            context["receipt"]["revision"],
        )
        self.assertFalse(cache_dir.exists())
        archives = list(
            (
                self.course
                / ".book-grilling"
                / "history"
                / "prefetch"
            ).glob("unit-two-r*")
        )
        self.assertEqual(len(archives), 1)
        self.assertTrue((archives[0] / "archive.json").is_file())

    def test_existing_course_without_prefetch_is_read_only_compatible(self) -> None:
        context = self.initialize()
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        state_path = self.course / ".book-grilling" / "course.json"
        page_path = self.course / "book-grilling.html"
        state_before = state_path.read_bytes()
        page_before = page_path.read_bytes()
        self.assertFalse(
            (self.course / ".book-grilling" / "prefetch").exists()
        )

        resumed = self.run_cli("context", self.course)
        self.assertEqual(resumed["receipt"], context["receipt"])
        self.assertEqual(resumed["prefetch"]["status"], "missing")
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(page_path.read_bytes(), page_before)
        audit = self.run_cli("audit", self.course)
        self.assertTrue(audit["ok"], audit["errors"])

    def test_invalid_review_cannot_unlock_or_mutate_course(self) -> None:
        context = self.initialize()
        tree = self.tree_one()
        review = self.review(
            "unit_tree",
            tree,
            tree["source_text_sha256"],
            "unit-one",
        )
        review["checks"]["answers_supported"] = False
        before = (self.course / ".book-grilling" / "course.json").read_bytes()
        error = self.run_cli(
            "prepare-unit",
            self.course,
            "--tree",
            self.write_json("bad-tree.json", tree),
            "--review",
            self.write_json("bad-review.json", review),
            "--source-text",
            self.unit_one,
            "--expected-revision",
            context["receipt"]["revision"],
            "--expected-unit",
            "unit-one",
            ok=False,
        )
        self.assertIn("checks are incomplete or failed", error)
        self.assertEqual(
            before,
            (self.course / ".book-grilling" / "course.json").read_bytes(),
        )
        self.assertNotIn(
            "当前可见答案",
            (self.course / "book-grilling.html").read_text(encoding="utf-8"),
        )

    def test_audit_detects_tampered_exact_unit_text(self) -> None:
        context = self.initialize()
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        evidence = self.course / ".book-grilling" / "units" / "unit-one.txt"
        evidence.write_text("被篡改的文本", encoding="utf-8")
        audit = self.run_cli("audit", self.course)
        self.assertFalse(audit["ok"])
        self.assertTrue(
            any("tree is invalid" in item for item in audit["errors"]),
            audit["errors"],
        )
        render_error = self.run_cli("render", self.course, ok=False)
        self.assertIn("Cannot render an invalid course", render_error)

    def test_invalidation_archives_affected_branch_and_hides_answers(self) -> None:
        final = self.complete_course()
        context = self.run_cli(
            "invalidate-unit",
            self.course,
            "--unit",
            "unit-one",
            "--reason",
            "发现第一单元证据范围错误",
            "--expected-revision",
            final["receipt"]["revision"],
        )
        self.assertEqual(context["need"], "prepare_current_unit")
        state = json.loads(
            (self.course / ".book-grilling" / "course.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["unit_records"]["unit-one"]["status"], "invalid")
        self.assertEqual(state["unit_records"]["unit-two"]["status"], "future")
        self.assertIsNone(state["synthesis"])
        archives = list((self.course / ".book-grilling" / "history").glob("*.json"))
        self.assertEqual(len(archives), 2)
        page = (self.course / "book-grilling.html").read_text(encoding="utf-8")
        self.assertNotIn("LOCKED_SECRET_", page)

    def test_manifest_rejects_partial_without_note_order_drift_and_overlap(self) -> None:
        partial = self.manifest(coverage_scope="partial")
        error = self.run_cli(
            "init",
            self.root / "partial-course",
            "--manifest",
            self.write_json("partial.json", partial),
            ok=False,
        )
        self.assertIn("coverage_note is required", error)

        out_of_order = self.manifest()
        out_of_order["source_units"][1]["sequence"] = 2
        out_of_order["source_units"][2]["sequence"] = 1
        error = self.run_cli(
            "init",
            self.root / "order-course",
            "--manifest",
            self.write_json("order.json", out_of_order),
            ok=False,
        )
        self.assertIn("author's source order", error)

        overlap_units = [
            {
                "id": "chapter",
                "parent_id": "",
                "position": 1,
                "kind": "章",
                "title": "一章",
                "locator": "全章",
                "learning_unit": True,
                "sequence": 1,
                "split_origin": "author",
                "estimated_tokens": 50,
            },
            {
                "id": "section",
                "parent_id": "chapter",
                "position": 1,
                "kind": "节",
                "title": "一节",
                "locator": "第一节",
                "learning_unit": True,
                "sequence": 2,
                "split_origin": "author",
                "estimated_tokens": 25,
            },
        ]
        error = self.run_cli(
            "init",
            self.root / "overlap-course",
            "--manifest",
            self.write_json(
                "overlap.json",
                self.manifest(source_units=overlap_units),
            ),
            ok=False,
        )
        self.assertIn("ancestor and descendant", error)


if __name__ == "__main__":
    unittest.main()
