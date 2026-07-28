from __future__ import annotations

import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL = SKILL_DIR / "SKILL.md"
CONTRACT = SKILL_DIR / "references" / "response-contract.md"
UNIT_PREPARATION = SKILL_DIR / "references" / "unit-preparation.md"
README = SKILL_DIR / "README.md"
VERSION = SKILL_DIR / "VERSION"
MAP_TEMPLATE = SKILL_DIR / "templates" / "map-template-v7.html"
PROGRESS_TEMPLATE = SKILL_DIR / "templates" / "progress-template-v2.html"
RUNTIME = SKILL_DIR / "scripts" / "sml.py"


class SkillResponseContractTests(unittest.TestCase):
    def test_skill_loads_the_response_contract(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "[response-contract.md](references/response-contract.md)",
            skill,
        )
        self.assertIn(
            "[unit-preparation.md](references/unit-preparation.md)",
            skill,
        )
        self.assertIn("at most one local runtime call", skill)
        self.assertIn("no PDF extraction", skill)
        self.assertIn("Reuse across several", skill)
        self.assertIn("turns is allowed", skill)
        self.assertIn("exactly one useful learner move", skill)
        self.assertIn("map link alone on the final", skill)
        self.assertLess(len(skill.encode("utf-8")), 15000)

    def test_contract_contains_confirmed_routine_constraints(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        required = [
            "shortest sufficient exact source span",
            "exactly one meaningful learner move",
            "on the final line",
            "at most one essential new term",
            "at most one main example",
            "smaller scaffold attempt",
            "two to five atomic steps",
            "previous result → current problem → current result → next pressure",
            "source wording → faithful translation → teacher explanation",
            "The teacher supplies the complete account",
            "Do not display page, chapter, edition",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)

    def test_every_learner_move_closes_before_continuation(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        course_model = (
            SKILL_DIR / "references" / "course-model.md"
        ).read_text(encoding="utf-8")
        map_contract = (
            SKILL_DIR / "references" / "map-contract.md"
        ).read_text(encoding="utf-8")
        combined = "\n".join((skill, contract, course_model, map_contract))
        required = [
            "normalized resolution near the top",
            "hidden expected answer word for word",
            "accepted parts",
            "one missing connection",
            "must not teach and test a different one",
            "Atomicity is learner-relative",
            "presentation cap",
            "repair substate",
            "not a sixth phase",
            "Prompt and explanation defects create no learner evidence",
            "Never serialize an open move's expected answer",
            "last normalized resolution is shown near the top",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_questions_pass_an_answerability_gate(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        combined = f"{skill}\n{contract}"
        required = [
            "new authorial content",
            "derivable relation",
            "mastery evidence",
            "Learner-move eligibility gate",
            "silently draft its expected answer",
            "Every required premise",
            "merely repeating the prompt",
            "this distinction",
            "how does this help you explain",
            "Normative, psychological, and ontological levels",
            "concrete case → plain-language relation → author term → boundary",
            "At a transition",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_unit_question_seeds_are_candidates_not_commands(self) -> None:
        preparation = UNIT_PREPARATION.read_text(encoding="utf-8")
        required = [
            "candidate learner move",
            "every premise was supplied",
            "scope boundary",
            "never authoritative",
            "latest reasoning",
            "expected answer",
            "required premises",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, preparation)

    def test_contract_defines_critical_reading_and_transfer(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        required = [
            "Critical reading is not compulsory opposition",
            "Do not rotate through a fixed checklist",
            "two or three connected conclusions",
            "source relation → case facts → justified judgment → boundary or disanalogy",
            "Reject a surface analogy",
            "correct_distinction",
            "correct_transfer",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    phrase in skill or phrase in contract,
                    f"Missing policy phrase: {phrase}",
                )

    def test_transfer_uses_domain_neutral_quality_gates(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        combined = f"{skill}\n{contract}"
        required = [
            "No domain is automatically allowed or forbidden",
            "structural",
            "factual reliability",
            "risk",
            "privacy",
            "skip transfer",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertNotIn(
            "Never generate or select AI, work, workplace, business, product, or operations",
            combined,
        )
        self.assertIn("Verify time-sensitive or disputed facts", contract)

    def test_five_phase_cycle_is_unified_and_evidence_driven(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        course_model = (
            SKILL_DIR / "references" / "course-model.md"
        ).read_text(encoding="utf-8")
        map_contract = (
            SKILL_DIR / "references" / "map-contract.md"
        ).read_text(encoding="utf-8")
        combined = "\n".join((skill, contract, course_model, map_contract))
        for phase in [
            "understanding",
            "verification",
            "critical",
            "transfer",
            "synthesis",
        ]:
            with self.subTest(phase=phase):
                self.assertIn(phase, combined)
        self.assertIn("Transitions depend on evidence, not turn count", skill)
        self.assertIn("current local learning-cycle phase", map_contract)
        self.assertIn("Immediate prompted completion establishes at most", contract)

    def test_contract_is_mode_sensitive(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        course_model = (
            SKILL_DIR / "references" / "course-model.md"
        ).read_text(encoding="utf-8")
        for mode in ["theory", "history", "practical", "literature", "mixed"]:
            with self.subTest(mode=mode):
                self.assertIn(mode, course_model)
        self.assertIn("reading-mode-appropriate", contract)
        self.assertIn("compatibility names", skill)
        self.assertIn("Do not convert chronology into deduction", course_model)

    def test_current_views_use_mode_sensitive_language(self) -> None:
        map_template = MAP_TEMPLATE.read_text(encoding="utf-8")
        progress_template = PROGRESS_TEMPLATE.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const modeCopyByMode", map_template)
        self.assertIn("const nodeTypeLabelsByMode", map_template)
        for mode in ["theory", "history", "practical", "literature", "mixed"]:
            with self.subTest(mode=mode):
                self.assertIn(f"{mode}: {{", map_template)
        self.assertIn("{{MASTERY_UNIT}}", progress_template)
        self.assertIn("{{MASTERY_LABEL}}", progress_template)
        self.assertIn('"history": ("条关键历史关系", "历史关系掌握")', runtime)

    def test_documentation_and_version_are_updated(self) -> None:
        self.assertEqual(VERSION.read_text(encoding="utf-8").strip(), "7.5.0")
        readme = README.read_text(encoding="utf-8")
        self.assertIn("# Socratic Map Learning 7.5.0", readme)
        self.assertIn("response-contract.md", readme)
        self.assertIn("unit-preparation.md", readme)
        self.assertIn("progress-template-v2.html", readme)
        self.assertNotIn("map-template-v5.html", readme)
        self.assertNotIn("map-template-v6.html", readme)
        self.assertNotIn("progress-template-v1.html", readme)

    def test_unit_preparation_defines_bounded_cache(self) -> None:
        preparation = UNIT_PREPARATION.read_text(encoding="utf-8")
        self.assertIn("smallest source range", preparation)
        self.assertIn("1–12", preparation)
        self.assertIn("prepare-unit", preparation)
        self.assertIn("one-call fast path", preparation)
        self.assertIn('"full_text"', preparation)
        self.assertIn('"expected_answer"', preparation)
        self.assertIn('"required_premises"', preparation)


if __name__ == "__main__":
    unittest.main()
