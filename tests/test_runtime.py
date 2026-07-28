from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
SML = SKILL_DIR / "scripts" / "sml.py"
VALIDATOR = SKILL_DIR / "scripts" / "validate_learning_map.py"
EXAMPLE = SKILL_DIR / "templates" / "course-blueprint.example.json"
SMOKE = SKILL_DIR / "tests" / "map_runtime_smoke.js"
GEOMETRY_AUDIT = SKILL_DIR / "tests" / "map_geometry_audit.js"
CONTRAST_AUDIT = SKILL_DIR / "tests" / "map_contrast_audit.js"


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sml-tests-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(
        self,
        *arguments: str,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["python3", str(SML), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def initialize(self, course_dir: Path) -> dict:
        result = self.run_cli(
            "init",
            str(course_dir),
            "--blueprint",
            str(EXAMPLE),
            "--map-path",
            str(course_dir / "map.html"),
        )
        return json.loads(result.stdout)

    def context(self, course_dir: Path) -> dict:
        return json.loads(
            self.run_cli("context", str(course_dir)).stdout
        )

    def test_transactional_learning_loop_and_rollback(self) -> None:
        course = self.root / "course"
        initialized = self.initialize(course)
        self.assertEqual(initialized["receipt"]["revision"], 0)
        self.assertEqual(
            initialized["receipt"]["current_node_id"],
            "node-question",
        )
        progress_path = Path(initialized["progress_path"])
        self.assertTrue(progress_path.is_file())
        self.assertEqual(initialized["unit_packet"]["status"], "missing")
        self.assertEqual(
            initialized["learning_cycle"]["current_phase"],
            "understanding",
        )

        self.run_cli(
            "commit",
            str(course),
            "--expected-revision",
            "0",
            "--expected-current",
            "node-question",
            "--diagnosis",
            "mastered",
            "--evidence-kind",
            "none",
            expected=2,
        )
        self.assertEqual(self.context(course)["receipt"]["revision"], 0)

        first = json.loads(
            self.run_cli(
                "commit",
                str(course),
                "--expected-revision",
                "0",
                "--expected-current",
                "node-question",
                "--diagnosis",
                "mastered",
                "--evidence-kind",
                "own_words_reason",
                "--relation-edge",
                "edge-question-criterion",
                "--relation-level",
                "reconstructable",
            ).stdout
        )
        self.assertEqual(first["receipt"]["revision"], 1)
        self.assertEqual(first["receipt"]["current_node_id"], "node-criterion")
        self.assertEqual(
            first["learning_cycle"]["current_phase"],
            "understanding",
        )
        self.assertEqual(
            first["semantic_relations"]["incoming"][0]["from"],
            "node-question",
        )
        self.assertEqual(
            first["semantic_relations"]["incoming"][0]["label"],
            "需要判断标准",
        )
        self.assertEqual(
            first["semantic_relations"]["incoming"][0]["mastery_level"],
            "reconstructable",
        )

        partial = json.loads(
            self.run_cli(
                "commit",
                str(course),
                "--expected-revision",
                "1",
                "--expected-current",
                "node-criterion",
                "--diagnosis",
                "partial",
                "--evidence-kind",
                "none",
                "--learning-phase",
                "verification",
            ).stdout
        )
        self.assertEqual(partial["receipt"]["revision"], 2)
        self.assertEqual(partial["receipt"]["current_node_id"], "node-criterion")
        self.assertEqual(
            partial["learning_cycle"]["current_phase"],
            "verification",
        )

        self.run_cli(
            "commit",
            str(course),
            "--expected-revision",
            "1",
            "--expected-current",
            "node-criterion",
            "--diagnosis",
            "mastered",
            "--evidence-kind",
            "correct_distinction",
            expected=2,
        )
        after_stale = self.context(course)
        self.assertEqual(after_stale["receipt"]["revision"], 2)
        self.assertEqual(
            after_stale["receipt"]["current_node_id"],
            "node-criterion",
        )

        second = json.loads(
            self.run_cli(
                "commit",
                str(course),
                "--expected-revision",
                "2",
                "--expected-current",
                "node-criterion",
                "--diagnosis",
                "mastered",
                "--evidence-kind",
                "correct_distinction",
            ).stdout
        )
        self.assertEqual(second["receipt"]["current_node_id"], "node-conclusion")

        completed = json.loads(
            self.run_cli(
                "commit",
                str(course),
                "--expected-revision",
                "3",
                "--expected-current",
                "node-conclusion",
                "--diagnosis",
                "mastered",
                "--evidence-kind",
                "correct_transfer",
            ).stdout
        )
        self.assertTrue(completed["complete"])
        self.assertEqual(completed["progress"]["current"], 0)
        validation = json.loads(
            self.run_cli("validate", str(course), "--deep").stdout
        )
        self.assertTrue(validation["ok"])

        map_text = (course / "map.html").read_text(encoding="utf-8")
        progress_text = progress_path.read_text(encoding="utf-8")
        self.assertEqual(
            stat.S_IMODE((course / "map.html").stat().st_mode),
            0o644,
        )
        self.assertIn('data-sml-version="7"', map_text)
        self.assertIn('id="source-sidebar"', map_text)
        self.assertIn('id="source-panel"', map_text)
        self.assertIn('id="spine-panel"', map_text)
        self.assertIn('id="main-content"', map_text)
        self.assertIn('id="content"', map_text)
        self.assertIn('id="graph-data"', map_text)
        self.assertIn("学习进度", map_text)
        self.assertIn(progress_path.name, map_text)
        self.assertNotIn('id="graph-viewport"', map_text)
        self.assertNotIn('id="graph-svg"', map_text)
        self.assertNotIn("function setZoomAt(", map_text)
        self.assertNotIn('"pointerdown"', map_text)
        self.assertIn('<div class="proof-arrow" aria-hidden="true">↑</div>', map_text)
        self.assertIn('<div class="premise-row">', map_text)
        self.assertIn("因此必须追问", map_text)
        self.assertIn("premise_ids", map_text)
        self.assertIn("conclusion_id", map_text)
        self.assertNotIn("history.pushState(", map_text)
        self.assertIn("function renderSourceNavigation(", map_text)
        self.assertIn("function renderQuestionPage(", map_text)
        self.assertIn("function renderReasoning(", map_text)
        self.assertIn("function phaseChip(", map_text)
        self.assertIn("function sourceReading(", map_text)
        self.assertIn("最近验证", map_text)
        self.assertNotIn("查看本单元导读", map_text)
        self.assertNotIn("unit-overview-link", map_text)
        self.assertNotIn("局部关系图", map_text)
        self.assertNotIn("这个回答凭什么成立", map_text)
        self.assertNotIn("阅读规则", map_text)
        self.assertNotIn("SOURCE-GROUNDED READING", map_text)
        self.assertNotIn("阅读入口", map_text)
        question_renderer = map_text[
            map_text.index("function renderQuestionPage("):
            map_text.index("function closeSidebar(")
        ]
        self.assertLess(
            question_renderer.index("${renderProofFor(stage)}"),
            question_renderer.index('<section class="question-context"'),
        )
        self.assertLess(
            question_renderer.index('<section class="question-context"'),
            question_renderer.index("${chainContext(stage)}"),
        )
        self.assertIn('"edge-question-criterion"', map_text)
        self.assertIn("需要判断标准", map_text)
        self.assertIn('data-sml-progress="2"', progress_text)
        self.assertIn('id="reading-progress"', progress_text)
        self.assertIn('id="mastery-progress"', progress_text)
        self.assertIn('id="source-timeline"', progress_text)
        self.assertIn('data-revision="4"', progress_text)
        smoke = subprocess.run(
            ["node", str(SMOKE), str(course / "map.html")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(smoke.returncode, 0, msg=smoke.stderr)
        self.assertIn("OK v7", smoke.stdout)
        geometry = subprocess.run(
            ["node", str(GEOMETRY_AUDIT), str(course / "map.html")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            geometry.returncode,
            0,
            msg=f"stdout:\n{geometry.stdout}\nstderr:\n{geometry.stderr}",
        )
        contrast = subprocess.run(
            ["node", str(CONTRAST_AUDIT), str(course / "map.html")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            contrast.returncode,
            0,
            msg=f"stdout:\n{contrast.stdout}\nstderr:\n{contrast.stderr}",
        )
        self.assertIn("OK proof-pages", geometry.stdout)

        audit = json.loads(
            self.run_cli("audit", str(course)).stdout
        )
        self.assertEqual(audit["metrics"]["semantic_edges"], 2)
        self.assertEqual(audit["metrics"]["lesson_route_edges"], 2)
        self.assertTrue(audit["ok"])

    def test_prepare_unit_caches_source_once_without_advancing(self) -> None:
        course = self.root / "prepared"
        initialized = self.initialize(course)
        packet_path = course / "unit-packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "current_node_id": "node-question",
                    "unit_title": "判断标准",
                    "excerpts": [
                        {
                            "id": "criterion",
                            "text": "可靠知识需要一个能够排除任意性的判断标准。",
                            "full_text": "只要知识主张仍可任意改变，可靠知识就需要一个能够排除任意性的判断标准。",
                            "translation": "可靠知识必须排除任意改变。",
                            "connection": "提出课程的首个必要问题。",
                            "interaction_kind": "distinguish",
                            "expected_answer": "判断标准排除任意性。",
                            "required_premises": [
                                "任意改变的主张不能成为可靠知识。"
                            ],
                            "scope_boundary": "不能据此推出唯一判断标准。",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        prepared = json.loads(
            self.run_cli(
                "prepare-unit",
                str(course),
                "--packet",
                str(packet_path),
                "--expected-revision",
                "0",
                "--expected-current",
                "node-question",
            ).stdout
        )
        self.assertEqual(prepared["receipt"], initialized["receipt"])
        self.assertEqual(prepared["unit_packet"]["status"], "ready")
        self.assertEqual(
            prepared["unit_packet"]["excerpts"][0]["id"],
            "criterion",
        )
        self.assertEqual(prepared["unit_packet"]["version"], 2)
        self.assertEqual(
            prepared["unit_packet"]["excerpts"][0]["required_premises"],
            ["任意改变的主张不能成为可靠知识。"],
        )
        self.assertEqual(prepared["prepared_unit"]["excerpt_count"], 1)

        committed = json.loads(
            self.run_cli(
                "commit",
                str(course),
                "--expected-revision",
                "0",
                "--expected-current",
                "node-question",
                "--diagnosis",
                "partial",
                "--evidence-kind",
                "none",
                "--learning-phase",
                "verification",
            ).stdout
        )
        self.assertEqual(committed["unit_packet"]["status"], "ready")
        self.assertNotIn("excerpts", committed["unit_packet"])
        self.assertEqual(
            committed["learning_cycle"]["current_phase"],
            "verification",
        )

        fresh = self.context(course)
        self.assertEqual(fresh["unit_packet"]["status"], "ready")
        self.assertEqual(
            fresh["unit_packet"]["excerpts"][0]["text"],
            "可靠知识需要一个能够排除任意性的判断标准。",
        )
        map_text = (course / "map.html").read_text(encoding="utf-8")
        self.assertIn("只要知识主张仍可任意改变", map_text)
        self.assertIn("可靠知识必须排除任意改变", map_text)
        self.assertNotIn("判断标准排除任意性", map_text)
        self.assertIn('"current_phase":"verification"', map_text)

    def test_history_mode_changes_current_view_language(self) -> None:
        course = self.root / "history-mode"
        course.mkdir()
        blueprint = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        blueprint["course"]["id"] = "history-mode"
        blueprint["argument_atlas"]["source_structure"] = {
            "version": 1,
            "label": "原书结构",
            "unit_term": "时期／章",
            "work_mode": "history",
            "units": [
                {
                    "id": "unit-course",
                    "position": 1,
                    "parent_id": "",
                    "kind": "period",
                    "title": "全书",
                    "summary": "历史问题所在单元。",
                    "source_refs": ["source-foundation"],
                }
            ],
        }
        for stage in blueprint["argument_atlas"]["system_spine"]["stages"]:
            stage["primary_unit_id"] = "unit-course"
            stage["related_unit_ids"] = []
        blueprint_path = course / "blueprint.json"
        blueprint_path.write_text(
            json.dumps(blueprint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        initialized = json.loads(
            self.run_cli(
                "init",
                str(course),
                "--blueprint",
                str(blueprint_path),
                "--map-path",
                str(course / "map.html"),
            ).stdout
        )
        map_text = (course / "map.html").read_text(encoding="utf-8")
        progress_text = Path(initialized["progress_path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn('"work_mode":"history"', map_text)
        self.assertIn("本问结果／解释", map_text)
        self.assertIn("竞争解释", map_text)
        self.assertIn("条关键历史关系", progress_text)
        self.assertIn('aria-label="历史关系掌握"', progress_text)

    def test_extend_compiled_frontier(self) -> None:
        course = self.root / "extended"
        self.initialize(course)
        fragment = {
            "sections": [],
            "source_anchors": [],
            "semantic_edges": [
                {
                    "id": "edge-conclusion-review",
                    "from": "node-conclusion",
                    "to": "node-review",
                    "relation": "requires",
                    "label": "需要回顾",
                    "rationale": "掌握结论以后，通过回顾检验整条论证能否被复原。",
                    "source_refs": ["source-argument"],
                }
            ],
            "nodes": [
                {
                    "id": "node-review",
                    "parent": "node-conclusion",
                    "section": "argument",
                    "position": 4,
                    "relation": "entails",
                    "title": "回顾完整论证",
                    "summary": "从总问题重新推出最终结论",
                    "detail": "学习者需要重新连接所有已掌握的依赖。",
                    "bridge": "承接核心结论。",
                    "next": "完成课程。",
                    "mastery_criterion": "学习者能在不看地图时复原三步论证。",
                    "prerequisites": [],
                    "source_refs": ["source-argument"],
                    "common_confusions": [],
                    "allowed_next": [],
                    "is_final": True,
                    "preview": False,
                }
            ],
            "set_final": {"node-conclusion": False},
            "add_allowed_next": {"node-conclusion": ["node-review"]},
        }
        fragment_path = course / "fragment.json"
        fragment_path.parent.mkdir(parents=True, exist_ok=True)
        fragment_path.write_text(
            json.dumps(fragment, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        extended = json.loads(
            self.run_cli(
                "extend",
                str(course),
                "--fragment",
                str(fragment_path),
            ).stdout
        )
        self.assertEqual(extended["receipt"]["revision"], 1)
        self.assertIn("node-review", extended["extended"]["nodes"])
        validation = json.loads(
            self.run_cli("validate", str(course)).stdout
        )
        self.assertTrue(validation["ok"])

    def test_current_map_reveals_new_ground_without_unlocking_future_map(
        self,
    ) -> None:
        course = self.root / "current-map-ground"
        self.initialize(course)
        self.run_cli(
            "commit",
            str(course),
            "--expected-revision",
            "0",
            "--expected-current",
            "node-question",
            "--diagnosis",
            "mastered",
            "--evidence-kind",
            "own_words_reason",
        )
        self.run_cli(
            "commit",
            str(course),
            "--expected-revision",
            "1",
            "--expected-current",
            "node-criterion",
            "--diagnosis",
            "mastered",
            "--evidence-kind",
            "correct_distinction",
        )
        fragment_path = course / "fragment.json"
        fragment_path.write_text(
            json.dumps(
                {
                    "sections": [],
                    "source_anchors": [],
                    "semantic_edges": [
                        {
                            "id": "edge-new-ground-conclusion",
                            "from": "node-new-ground",
                            "to": "node-conclusion",
                            "relation": "grounds",
                            "label": "提供当前根据",
                            "rationale": "新编译的材料为当前结论提供根据。",
                            "source_refs": ["source-argument"],
                            "origin": "reviewed",
                        }
                    ],
                    "nodes": [
                        {
                            "id": "node-new-ground",
                            "node_type": "claim",
                            "parent": "node-conclusion",
                            "section": "argument",
                            "position": 4,
                            "relation": "grounds",
                            "title": "当前论证中新编译的根据",
                            "summary": "当前材料应当可见",
                            "detail": "它还不是路线目标，也没有被判定为掌握。",
                            "bridge": "它支持当前结论。",
                            "next": "继续重建当前关系。",
                            "mastery_criterion": "学习者能说明它如何支持结论。",
                            "prerequisites": [],
                            "source_refs": ["source-argument"],
                            "common_confusions": [],
                            "allowed_next": ["node-conclusion"],
                            "is_final": False,
                            "frontier_open": False,
                            "preview": False,
                        }
                    ],
                    "set_final": {},
                    "add_allowed_next": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.run_cli(
            "extend",
            str(course),
            "--fragment",
            str(fragment_path),
        )

        blueprint = json.loads(
            (course / ".socratic-map" / "blueprint.json").read_text(
                encoding="utf-8"
            )
        )
        atlas = blueprint["argument_atlas"]
        current_map = next(
            item
            for item in atlas["maps"]
            if item["id"] == "map-main-argument"
        )
        current_map["node_ids"].append("node-new-ground")
        atlas["inferences"].append(
            {
                "id": "inference-new-ground",
                "map_id": "map-main-argument",
                "premise_ids": ["node-new-ground"],
                "conclusion_id": "node-conclusion",
                "bridge": "新根据支持当前结论。",
                "kind": "supports",
                "source_refs": ["source-argument"],
                "mastery_edge_ids": [],
                "origin": "reviewed",
            }
        )
        overlay_path = course / "overlay.json"
        overlay_path.write_text(
            json.dumps(
                {"argument_atlas": atlas},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.run_cli(
            "structure",
            str(course),
            "--overlay",
            str(overlay_path),
        )

        map_text = (course / "map.html").read_text(encoding="utf-8")
        marker = '<script type="application/json" id="graph-data">'
        graph_json = map_text.split(marker, 1)[1].split("</script>", 1)[0]
        graph = json.loads(graph_json)
        node_lookup = {item["id"]: item for item in graph["nodes"]}
        self.assertEqual(node_lookup["node-new-ground"]["status"], "future")
        self.assertFalse(node_lookup["node-new-ground"]["answer_hidden"])
        future_stage = next(
            item
            for item in graph["argument_atlas"]["system_spine"]["stages"]
            if item["id"] == "stage-future-transfer"
        )
        self.assertEqual(future_stage["status"], "future")
        self.assertEqual(future_stage["answer_id"], "")

    def test_structure_overlay_separates_knowledge_graph_from_lesson_route(self) -> None:
        course = self.root / "structured"
        self.initialize(course)
        reviewed_source = course / "reviewed-source.txt"
        reviewed_source.write_text(
            "reviewed authoritative source",
            encoding="utf-8",
        )
        overlay = {
            "course_source": {
                "kind": "file",
                "locator": str(reviewed_source),
                "edition": "reviewed test edition",
            },
            "sections_upsert": [
                {
                    "id": "synthesis",
                    "title": "综合关系",
                    "summary": "跨章节整合",
                    "position": 3,
                }
            ],
            "node_updates": {
                "node-conclusion": {
                    "section": "synthesis",
                }
            },
            "replace_semantic_edges": True,
            "semantic_edges": [
                {
                    "id": "edge-question-criterion",
                    "from": "node-question",
                    "to": "node-criterion",
                    "relation": "answers",
                    "label": "回答总问题",
                    "rationale": "最终结论直接回应课程总问题。",
                    "source_refs": ["source-argument"],
                },
                {
                    "id": "edge-criterion-conclusion",
                    "from": "node-criterion",
                    "to": "node-conclusion",
                    "relation": "grounds",
                    "label": "提供双重根据",
                    "rationale": "判断标准为最终结论提供形式和对象两方面根据。",
                    "source_refs": ["source-argument"],
                },
            ],
        }
        overlay_path = course / "overlay.json"
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        structured = json.loads(
            self.run_cli(
                "structure",
                str(course),
                "--overlay",
                str(overlay_path),
            ).stdout
        )
        self.assertEqual(structured["structured"]["semantic_edges"], 2)
        self.assertEqual(
            structured["structured"]["node_updates"],
            ["node-conclusion"],
        )
        context = self.context(course)
        self.assertEqual(context["receipt"]["current_node_id"], "node-question")
        self.assertEqual(
            context["course"]["source"]["locator"],
            str(reviewed_source),
        )
        self.assertTrue(context["course"]["source"]["sha256"])
        map_text = (course / "map.html").read_text(encoding="utf-8")
        self.assertIn("综合关系", map_text)
        self.assertIn("回答总问题", map_text)

    def test_v7_html_validator_requires_source_navigation(self) -> None:
        course = self.root / "html-contract"
        self.initialize(course)
        map_path = course / "map.html"
        valid = subprocess.run(
            ["python3", str(VALIDATOR), str(map_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid.returncode, 0, msg=valid.stderr)

        broken = map_path.read_text(encoding="utf-8")
        broken = broken.replace('id="source-sidebar"', 'id="detail-sidebar"')
        broken = broken.replace(
            '"conclusion_id":"node-criterion"',
            '"conclusion_id":"node-missing"',
            1,
        )
        broken_path = course / "broken.html"
        broken_path.write_text(broken, encoding="utf-8")
        invalid = subprocess.run(
            ["python3", str(VALIDATOR), str(broken_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("source-structure sidebar", invalid.stderr)

    def test_deep_validation_detects_source_change(self) -> None:
        course = self.root / "source-check"
        source = course / "source.txt"
        course.mkdir(parents=True)
        source.write_text("authoritative version one", encoding="utf-8")
        blueprint = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        blueprint["course"]["id"] = "source-check"
        blueprint["course"]["source"] = {
            "kind": "file",
            "locator": str(source),
            "edition": "test",
        }
        blueprint_path = course / "blueprint.json"
        blueprint_path.write_text(
            json.dumps(blueprint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.run_cli(
            "init",
            str(course),
            "--blueprint",
            str(blueprint_path),
            "--map-path",
            str(course / "map.html"),
        )
        source.write_text("authoritative version two", encoding="utf-8")
        validation = json.loads(
            self.run_cli("validate", str(course), "--deep").stdout
        )
        self.assertFalse(validation["ok"])
        self.assertTrue(
            any("source hash changed" in error for error in validation["errors"])
        )

    def test_legacy_import_keeps_backup(self) -> None:
        course = self.root / "legacy"
        course.mkdir()
        legacy = course / "map.html"
        legacy.write_text(
            """<!doctype html>
<html lang="zh-CN">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    .knowledge-node:focus-visible { outline: 2px solid black; }
    @media (prefers-reduced-motion: reduce) { * { transition: none; } }
  </style>
</head>
<body>
  <a class="skip-link" href="#map">skip</a>
  <h1>Legacy Course</h1>
  <main id="map">
    <button id="node-root" class="knowledge-node mastered"
      data-parent="" data-status="已掌握" data-source="Section 1"
      data-title="Root" data-detail="Root detail"
      data-bridge="Start" data-next="Continue">Root</button>
    <button id="node-current" class="knowledge-node current"
      data-parent="node-root" data-status="正在学习" data-source="Section 2"
      data-title="Current" data-detail="Current detail"
      data-bridge="Root" data-next="Finish" aria-current="step">Current</button>
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )
        imported = json.loads(
            self.run_cli(
                "import-html",
                str(course),
                "--map",
                str(legacy),
                "--course-id",
                "legacy-course",
            ).stdout
        )
        backup = Path(imported["legacy_backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(
            imported["receipt"]["current_node_id"],
            "node-current",
        )
        self.assertTrue(imported["current"]["frontier_open"])
        self.assertFalse(imported["current"]["is_final"])
        self.run_cli(
            "commit",
            str(course),
            "--expected-revision",
            "0",
            "--expected-current",
            "node-current",
            "--diagnosis",
            "mastered",
            "--evidence-kind",
            "own_words_reason",
            expected=2,
        )
        self.assertEqual(self.context(course)["receipt"]["revision"], 0)
        validation = json.loads(
            self.run_cli("validate", str(course), "--deep").stdout
        )
        self.assertTrue(validation["ok"])


if __name__ == "__main__":
    unittest.main()
