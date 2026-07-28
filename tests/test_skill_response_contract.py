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
        self.assertIn("ask exactly one next question", skill)
        self.assertIn("place the stable clickable HTML map link alone on the final", skill)
        self.assertLess(len(skill.encode("utf-8")), 11000)

    def test_contract_contains_confirmed_routine_constraints(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        required = [
            "one exact source excerpt of one to three sentences",
            "exactly one question",
            "on the final line",
            "at most one essential new term",
            "at most one main example",
            "make at most one smaller scaffold attempt",
            "what the passage means in plain language",
            "what it receives from the preceding discussion",
            "The teacher supplies the complete account",
            "Do not display page, chapter, edition",
        ]
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)

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

    def test_transfer_uses_a_strict_source_whitelist(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        combined = f"{skill}\n{contract}"
        allowed = [
            "verified news or public events",
            "established historical knowledge or events",
            "ordinary, low-stakes interpersonal situations",
        ]
        for phrase in allowed:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertIn(
            "Never generate or select AI, work, workplace, business, product, or operations",
            contract,
        )
        self.assertIn("Verify time-sensitive or disputed news", contract)
        self.assertNotIn("public, work, news, AI, or interpersonal", combined)

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
        self.assertEqual(VERSION.read_text(encoding="utf-8").strip(), "7.2.0")
        readme = README.read_text(encoding="utf-8")
        self.assertIn("# Socratic Map Learning 7.2.0", readme)
        self.assertIn("response-contract.md", readme)
        self.assertIn("unit-preparation.md", readme)
        self.assertIn("progress-template-v2.html", readme)

    def test_unit_preparation_defines_bounded_cache(self) -> None:
        preparation = UNIT_PREPARATION.read_text(encoding="utf-8")
        self.assertIn("smallest source range", preparation)
        self.assertIn("1–12", preparation)
        self.assertIn("prepare-unit", preparation)
        self.assertIn("one-call fast path", preparation)


if __name__ == "__main__":
    unittest.main()
