# Learning-unit question tree and independent review

Read this only when context says `prepare_current_unit`, when `prefetch-context`
says `prepare_prefetch_unit`, when repairing an invalidated unit, or when the
source changed.

## Preparation sequence

1. Extract the exact complete text of the current learning unit into UTF-8.
2. Verify its first and last source spans, headings, paragraph continuity,
   encoding, tables, footnotes, and quotations.
3. Read the complete unit.
4. Identify the unit's governing question.
5. Decompose it into the questions needed to explain every substantive piece
   of knowledge in this unit.
6. Give every question one complete recommended answer and one exact excerpt.
7. Classify every source span in the coverage ledger.
8. Validate locally and fingerprint the exact text and normalized tree.
9. Ask a fresh independent reviewer to compare only the text and tree.
10. Repair every issue and repeat until the reviewer passes the exact hashes.

## Tree shape

- One root: `What is this unit trying to explain or establish?`
- Ordered children: its main subquestions.
- Deeper children: required distinctions, reasons, mechanisms, objections,
  replies, evidence, conditions, or boundaries.
- The runtime traverses depth-first in sibling order.
- Do not create concept, evidence, quotation, or taxonomy nodes. Express all
  knowledge as questions.
- Add a child only when it supplies a distinct explanatory move.

## Node contract

Each node contains:

```json
{
  "id": "q-root",
  "parent_id": "",
  "position": 1,
  "question": "这一单元总体要解决什么问题？",
  "recommended_answer": "一个完整、可独立理解的答案。",
  "provenance": "editorial_synthesis",
  "source": {
    "locator": "本单元第 1–3 段",
    "excerpt": "必须是 unit.txt 中完全一致的最短充分原文。"
  },
  "interpretive_note": "必要时说明整理、争议、翻译或范围；否则留空。"
}
```

Allowed provenance:

- `source_explicit` — the source states the answer directly;
- `editorial_synthesis` — the answer faithfully organizes several source spans;
- `external_context` — verified background, clearly separate from the work;
- `contested_interpretation` — an interpretation that must name the dispute.

The recommended answer may contain several closely connected steps, but only
one main answer. Split independently challengeable conclusions.

## Exact evidence

The displayed excerpt must:

- occur exactly in the extracted unit text;
- be the shortest span sufficient to check the answer;
- preserve qualifications and negation;
- never place a paraphrase inside quotation marks.

For translations, the current edition is authoritative. Add original-language
comparison only when the interpretation depends on it and identify the source.

## Coverage ledger

Classify the entire unit, not only the passages selected for questions:

```json
{
  "locator": "第 4–6 段",
  "disposition": "knowledge",
  "node_ids": ["q-distinction", "q-boundary"],
  "reason": "这三段建立核心区分并限定其范围。"
}
```

Allowed dispositions:

- `knowledge` — contributes substantive knowledge and names node ids;
- `context` — necessary orientation but no distinct question;
- `rhetorical` — repetition, transition, illustration, or style that adds no
  new substantive knowledge.

Every tree node must appear in at least one knowledge coverage item. Every unit
span must be classified. Uncertain spans block review; do not disguise them as
context or rhetoric.

## Tree artifact

```json
{
  "schema_version": 1,
  "unit_id": "unit-one",
  "title": "本单元问题树标题",
  "source_text_sha256": "<fingerprint of exact UTF-8 unit text>",
  "root_id": "q-root",
  "nodes": [],
  "coverage": []
}
```

Get hashes with:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  fingerprint --text-file <unit.txt>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  fingerprint --json-file <tree.json>
```

The JSON fingerprint used by the review must match the normalized artifact that
`prepare-unit` accepts. Run a local prepare in a temporary course when schema
normalization changes the artifact.

## Independent reviewer

Use a fresh agent/context when available. Give it:

- exact complete unit text;
- the candidate tree;
- this node and coverage contract;
- the review JSON schema below.

Do not give it the generator's reasoning, preferred verdict, suspected errors,
or prior repair explanation. The reviewer must actively try to falsify the
tree.

It checks:

1. source text is complete and usable;
2. every substantive span is represented;
3. each answer follows from its cited source;
4. no answer inflates scope, causality, necessity, or certainty;
5. the parent-child question structure is coherent;
6. every excerpt is exact;
7. authorial statement, editorial synthesis, background, and dispute are
   correctly identified.

Required passed review:

```json
{
  "schema_version": 1,
  "artifact_type": "unit_tree",
  "unit_id": "unit-one",
  "artifact_sha256": "<canonical normalized tree hash>",
  "source_text_sha256": "<exact unit text hash>",
  "verdict": "passed",
  "reviewed_at": "2026-07-29T12:00:00Z",
  "reviewer": {
    "independent": true,
    "method": "fresh independent source-to-tree review"
  },
  "checks": {
    "source_complete": true,
    "coverage_complete": true,
    "answers_supported": true,
    "no_scope_inflation": true,
    "tree_valid": true,
    "citations_exact": true
  },
  "issues": []
}
```

If independent review is unavailable, stop. Do not self-label the unit passed.

## Install or cache

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prepare-unit <course-dir> \
  --tree <tree.json> \
  --review <review.json> \
  --source-text <unit.txt> \
  --expected-revision <revision> \
  --expected-unit <unit-id>
```

The runtime preserves the exact unit text locally, installs the immutable
reviewed tree, marks only its root current, redacts locked answers from the
reader payload, and regenerates the page.

In a background prefetch session, do not run `prepare-unit`. Use `cache-unit`
as specified in [prefetch.md](prefetch.md). It validates the same artifacts but
does not change `course.json`, unlock a node, or regenerate the reader.
