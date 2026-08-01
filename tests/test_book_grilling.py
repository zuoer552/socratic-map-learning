from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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
            "第二单元解释乙。乙限定了甲的适用范围。\n\n"
            "第三单元解释丙。丙补充了乙的边界。\n\n"
            "第四单元解释丁。丁说明了最终条件。\n",
            encoding="utf-8",
        )
        self.unit_one_text = "第一单元解释甲。甲依赖一个必要条件。"
        self.unit_two_text = "第二单元解释乙。乙限定了甲的适用范围。"
        self.unit_three_text = "第三单元解释丙。丙补充了乙的边界。"
        self.unit_four_text = "第四单元解释丁。丁说明了最终条件。"
        self.unit_one = self.root / "unit-one.txt"
        self.unit_two = self.root / "unit-two.txt"
        self.unit_three = self.root / "unit-three.txt"
        self.unit_four = self.root / "unit-four.txt"
        self.unit_one.write_text(self.unit_one_text, encoding="utf-8")
        self.unit_two.write_text(self.unit_two_text, encoding="utf-8")
        self.unit_three.write_text(self.unit_three_text, encoding="utf-8")
        self.unit_four.write_text(self.unit_four_text, encoding="utf-8")

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

    def simple_tree(
        self,
        unit_id: str,
        source_text: str,
        label: str,
    ) -> dict:
        node_id = f"q-{unit_id}"
        return {
            "schema_version": 1,
            "unit_id": unit_id,
            "title": f"{label}问题树",
            "source_text_sha256": hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            "root_id": node_id,
            "nodes": [
                {
                    "id": node_id,
                    "parent_id": "",
                    "position": 1,
                    "question": f"{label}解释什么？",
                    "recommended_answer": f"{label}的完整推荐答案。",
                    "provenance": "editorial_synthesis",
                    "source": {
                        "locator": f"{label}全部",
                        "excerpt": source_text,
                    },
                    "interpretive_note": "这是对本单元关系的整理。",
                }
            ],
            "coverage": [
                {
                    "locator": f"{label}全部",
                    "disposition": "knowledge",
                    "node_ids": [node_id],
                    "reason": "完整覆盖本单元。",
                }
            ],
        }

    def multi_unit_manifest(self) -> dict:
        manifest = self.manifest()
        manifest["source_units"].extend(
            [
                {
                    "id": "unit-three",
                    "parent_id": "part-one",
                    "position": 3,
                    "kind": "章",
                    "title": "第三单元",
                    "locator": "第三段",
                    "learning_unit": True,
                    "sequence": 3,
                    "split_origin": "author",
                    "estimated_tokens": 30,
                },
                {
                    "id": "unit-four",
                    "parent_id": "part-one",
                    "position": 4,
                    "kind": "章",
                    "title": "第四单元",
                    "locator": "第四段",
                    "learning_unit": True,
                    "sequence": 4,
                    "split_origin": "author",
                    "estimated_tokens": 30,
                },
            ]
        )
        return manifest

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

    def plan_batch(
        self,
        *,
        mode: str = "remaining",
        batch_size: int = 5,
    ) -> dict:
        return self.run_cli(
            "prefetch-plan",
            self.course,
            "--mode",
            mode,
            "--batch-size",
            batch_size,
        )

    def claim(self, role: str, token: str) -> dict:
        return self.run_cli(
            "prefetch-claim",
            self.course,
            "--role",
            role,
            "--worker-token",
            token,
        )

    def stage_batch_unit(
        self,
        tree: dict,
        source_text_path: Path,
        unit: str,
        token: str,
    ) -> dict:
        return self.run_cli(
            "stage-prefetch-unit",
            self.course,
            "--tree",
            self.write_json(f"{unit}-batch-tree.json", tree),
            "--source-text",
            source_text_path,
            "--expected-unit",
            unit,
            "--worker-token",
            token,
        )

    def approve_batch_unit(
        self,
        tree: dict,
        source_text_path: Path,
        unit: str,
        reviewer_token: str,
    ) -> dict:
        review = self.review(
            "unit_tree",
            tree,
            tree["source_text_sha256"],
            unit,
        )
        return self.run_cli(
            "cache-unit",
            self.course,
            "--tree",
            self.write_json(f"{unit}-approved-tree.json", tree),
            "--review",
            self.write_json(f"{unit}-approved-review.json", review),
            "--source-text",
            source_text_path,
            "--expected-unit",
            unit,
            "--worker-token",
            reviewer_token,
        )

    def batch_prepare(
        self,
        tree: dict,
        source_text_path: Path,
        unit: str,
        generator_token: str,
        reviewer_token: str,
    ) -> dict:
        claimed = self.claim("generator", generator_token)
        self.assertEqual(claimed["unit_id"], unit)
        self.stage_batch_unit(
            tree,
            source_text_path,
            unit,
            generator_token,
        )
        claimed = self.claim("reviewer", reviewer_token)
        self.assertEqual(claimed["unit_id"], unit)
        return self.approve_batch_unit(
            tree,
            source_text_path,
            unit,
            reviewer_token,
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

    def test_batch_plan_claims_multiple_unique_units_without_progress_mutation(
        self,
    ) -> None:
        context = self.initialize(self.multi_unit_manifest())
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        state_path = self.course / ".book-grilling" / "course.json"
        page_path = self.course / "book-grilling.html"
        state_before = state_path.read_bytes()
        page_before = page_path.read_bytes()

        batch = self.plan_batch()
        self.assertEqual(batch["total"], 3)
        self.assertEqual(batch["counts"], {"queued": 3})
        def concurrent_claim(token: str) -> tuple[int, str, str]:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "prefetch-claim",
                    str(self.course),
                    "--role",
                    "generator",
                    "--worker-token",
                    token,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            return result.returncode, result.stdout, result.stderr

        with ThreadPoolExecutor(max_workers=3) as pool:
            raw_claims = list(
                pool.map(
                    concurrent_claim,
                    ("generator-a", "generator-b", "generator-c"),
                )
            )
        for returncode, _, stderr in raw_claims:
            self.assertEqual(returncode, 0, stderr)
        claimed = [json.loads(stdout) for _, stdout, _ in raw_claims]
        self.assertEqual(
            sorted(item["unit_id"] for item in claimed),
            ["unit-four", "unit-three", "unit-two"],
        )
        self.assertFalse(self.claim("generator", "generator-d")["claimed"])
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(page_path.read_bytes(), page_before)

    def test_batch_quality_gate_requires_distinct_reviewers_and_every_package(
        self,
    ) -> None:
        context = self.initialize(self.multi_unit_manifest())
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        state_path = self.course / ".book-grilling" / "course.json"
        page_path = self.course / "book-grilling.html"
        state_before = state_path.read_bytes()
        page_before = page_path.read_bytes()
        self.plan_batch()

        self.assertEqual(
            self.claim("generator", "generator-two")["unit_id"],
            "unit-two",
        )
        self.stage_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-two",
        )
        self.assertFalse(
            self.claim("reviewer", "generator-two")["claimed"]
        )
        self.assertEqual(
            self.claim("reviewer", "reviewer-two")["unit_id"],
            "unit-two",
        )
        error = self.run_cli(
            "cache-unit",
            self.course,
            "--tree",
            self.write_json("unit-two-wrong-worker-tree.json", self.tree_two()),
            "--review",
            self.write_json(
                "unit-two-wrong-worker-review.json",
                self.review(
                    "unit_tree",
                    self.tree_two(),
                    self.tree_two()["source_text_sha256"],
                    "unit-two",
                ),
            ),
            "--source-text",
            self.unit_two,
            "--expected-unit",
            "unit-two",
            "--worker-token",
            "generator-two",
            ok=False,
        )
        self.assertIn("belongs to another worker", error)
        result = self.approve_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "reviewer-two",
        )
        self.assertFalse(result["batch"]["complete"])
        self.assertEqual(result["batch"]["counts"]["ready"], 1)

        self.batch_prepare(
            self.simple_tree("unit-three", self.unit_three_text, "第三单元"),
            self.unit_three,
            "unit-three",
            "generator-three",
            "reviewer-three",
        )
        result = self.batch_prepare(
            self.simple_tree("unit-four", self.unit_four_text, "第四单元"),
            self.unit_four,
            "unit-four",
            "generator-four",
            "reviewer-four",
        )
        self.assertTrue(result["batch"]["complete"])
        self.assertEqual(result["batch"]["counts"], {"ready": 3})
        for unit_id in ("unit-two", "unit-three", "unit-four"):
            self.assertTrue(
                (
                    self.course
                    / ".book-grilling"
                    / "prefetch"
                    / "units"
                    / unit_id
                    / "package.json"
                ).is_file()
            )
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(page_path.read_bytes(), page_before)

    def test_interrupted_batch_review_resumes_from_staged_artifacts(self) -> None:
        context = self.initialize(self.multi_unit_manifest())
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.plan_batch(mode="next-batch", batch_size=1)
        self.claim("generator", "generator-two")
        staged = self.stage_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-two",
        )["staged"]
        staged_tree_before = Path(staged["tree_path"]).read_bytes()
        self.claim("reviewer", "reviewer-interrupted")

        resumed = self.run_cli("prefetch-resume", self.course)
        self.assertEqual(resumed["recovered_claims"], ["unit-two"])
        self.assertEqual(resumed["counts"], {"pending_review": 1})
        self.assertEqual(Path(staged["tree_path"]).read_bytes(), staged_tree_before)
        self.assertEqual(
            self.claim("reviewer", "reviewer-resumed")["unit_id"],
            "unit-two",
        )
        approved = self.approve_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "reviewer-resumed",
        )
        self.assertTrue(approved["batch"]["complete"])

    def test_failed_batch_review_requires_repair_before_ready(self) -> None:
        context = self.initialize(self.multi_unit_manifest())
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.plan_batch(mode="next-batch", batch_size=1)
        self.claim("generator", "generator-first")
        self.stage_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-first",
        )
        self.claim("reviewer", "reviewer-first")
        failed = self.review(
            "unit_tree",
            self.tree_two(),
            self.tree_two()["source_text_sha256"],
            "unit-two",
        )
        failed["verdict"] = "failed"
        failed["checks"]["answers_supported"] = False
        failed["issues"] = [
            {
                "check": "answers_supported",
                "message": "答案范围需要收紧。",
            }
        ]
        result = self.run_cli(
            "record-prefetch-review",
            self.course,
            "--review",
            self.write_json("failed-batch-review.json", failed),
            "--expected-unit",
            "unit-two",
            "--worker-token",
            "reviewer-first",
        )
        self.assertEqual(result["next"], "repair_and_restage")
        self.assertEqual(result["batch"]["counts"], {"repairing": 1})
        self.assertFalse(
            (
                self.course
                / ".book-grilling"
                / "prefetch"
                / "units"
                / "unit-two"
                / "package.json"
            ).exists()
        )

        self.claim("generator", "generator-repair")
        self.stage_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-repair",
        )
        self.claim("reviewer", "reviewer-second")
        approved = self.approve_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "reviewer-second",
        )
        self.assertTrue(approved["batch"]["complete"])

    def test_batch_refuses_to_stage_after_authoritative_source_changes(self) -> None:
        context = self.initialize(self.multi_unit_manifest())
        self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.plan_batch(mode="next-batch", batch_size=1)
        self.claim("generator", "generator-source-check")
        state_path = self.course / ".book-grilling" / "course.json"
        state_before = state_path.read_bytes()
        self.source.write_text(
            self.source.read_text(encoding="utf-8") + "\n来源发生变化。",
            encoding="utf-8",
        )
        error = self.run_cli(
            "stage-prefetch-unit",
            self.course,
            "--tree",
            self.write_json("changed-source-tree.json", self.tree_two()),
            "--source-text",
            self.unit_two,
            "--expected-unit",
            "unit-two",
            "--worker-token",
            "generator-source-check",
            ok=False,
        )
        self.assertIn("source fingerprint changed", error)
        self.assertEqual(state_path.read_bytes(), state_before)

    def test_multiple_ready_units_activate_in_order_and_a_hole_never_skips(
        self,
    ) -> None:
        context = self.initialize(self.multi_unit_manifest())
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.plan_batch()
        self.claim("generator", "generator-two")
        self.assertEqual(
            self.claim("generator", "generator-three")["unit_id"],
            "unit-three",
        )
        tree_three = self.simple_tree(
            "unit-three",
            self.unit_three_text,
            "第三单元",
        )
        self.stage_batch_unit(
            tree_three,
            self.unit_three,
            "unit-three",
            "generator-three",
        )
        self.claim("reviewer", "reviewer-three")
        self.approve_batch_unit(
            tree_three,
            self.unit_three,
            "unit-three",
            "reviewer-three",
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
        self.assertEqual(context["receipt"]["current_unit_id"], "unit-two")
        self.assertEqual(context["need"], "prepare_current_unit")
        self.assertIsNone(context["current_node"])
        self.assertEqual(context["prefetch_batch"]["counts"]["ready"], 1)

        self.run_cli("prefetch-resume", self.course)
        self.assertEqual(
            self.claim("generator", "generator-two-resumed")["unit_id"],
            "unit-two",
        )
        self.stage_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-two-resumed",
        )
        self.assertEqual(
            self.claim("reviewer", "reviewer-two")["unit_id"],
            "unit-two",
        )
        self.approve_batch_unit(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "reviewer-two",
        )
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
        context = self.commit(
            node="q-boundary",
            revision=context["receipt"]["revision"],
            unit="unit-two",
        )
        self.assertEqual(context["receipt"]["current_unit_id"], "unit-three")
        self.assertEqual(context["current_node"]["id"], "q-unit-three")

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

    def test_batch_invalidation_marks_jobs_stale_and_plan_requeues_them(self) -> None:
        context = self.initialize(self.multi_unit_manifest())
        context = self.prepare(
            self.tree_one(),
            self.unit_one,
            context["receipt"]["revision"],
            "unit-one",
        )
        self.plan_batch()
        self.batch_prepare(
            self.tree_two(),
            self.unit_two,
            "unit-two",
            "generator-two",
            "reviewer-two",
        )
        self.run_cli(
            "invalidate-unit",
            self.course,
            "--unit",
            "unit-one",
            "--reason",
            "第一单元边界需要重建",
            "--expected-revision",
            context["receipt"]["revision"],
        )
        status = self.run_cli("prefetch-status", self.course)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["counts"], {"stale": 3})
        replanned = self.plan_batch()
        self.assertEqual(replanned["counts"], {"queued": 4})
        self.assertFalse(replanned["complete"])

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
