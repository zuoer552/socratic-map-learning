# Runtime and JSON contract

Read this before constructing runtime input. The runtime uses only Python's
standard library.

Authoritative state:

```text
<course-dir>/.book-grilling/course.json
```

Derived reader:

```text
<course-dir>/book-grilling.html
```

The manifest source object must declare `coverage_scope` as `complete` or
`partial`. A partial source also requires a non-empty `coverage_note`; both are
carried into the public reader so completion cannot be overstated.

## Context receipt

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  context <course-dir>
```

The response includes:

- revision;
- current learning unit and question;
- next required action;
- completed/total units;
- reader path;
- bounded next-unit prefetch status.

Pass the exact receipt values to the next mutating call. Stale calls fail
without changing state.

If the current unit needs preparation and its cache is ready, top-level `need`
is `activate_prefetched_unit`.

## Bounded prefetch cache

Discover the eligible current-or-next target without user-supplied unit or page
parameters:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-context <course-dir>
```

After exact extraction, tree validation, and independent review, cache it:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  cache-unit <course-dir> \
  --tree <tree.json> \
  --review <review.json> \
  --source-text <unit.txt> \
  --expected-unit <unit-id>
```

This writes only
`.book-grilling/prefetch/units/<unit-id>/`. It does not edit authoritative
progress or the reader. The package binds the cache to the book id, source
fingerprint, immutable course structure, source-unit metadata, exact unit text,
normalized tree, and passed review.

Normally the final `commit` of the prior unit validates and installs the cache
atomically. When preparation completes after that boundary, activate it using
the current receipt:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  activate-prefetched-unit <course-dir> \
  --expected-revision <revision> \
  --expected-unit <unit-id>
```

Invalid, incomplete, missing, and stale caches never block a valid commit and
never unlock answers. `audit` reports optional-cache problems as warnings while
continuing to evaluate authoritative course validity.

## Turn update

Keep a live doubt on the current node:

```json
{
  "node_id": "q-current",
  "outcome": "open",
  "open_question": "仍然需要解决的具体疑问"
}
```

Resolve the current node:

```json
{
  "node_id": "q-current",
  "outcome": "resolved",
  "stance": "understood",
  "learner_note": "可选：学习者形成的简短理解"
}
```

Allowed stance:

- `understood`;
- `understood-but-disagrees`.

Commit:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  commit <course-dir> \
  --turn <turn.json> \
  --expected-revision <revision> \
  --expected-unit <unit-id> \
  --expected-node <node-id>
```

`commit` changes one node only, unlocks at most one next node, and regenerates
the page. Never call `render` after it.

## Book synthesis

```json
{
  "schema_version": 1,
  "question": "整本书最终试图回答什么？",
  "recommended_answer": "完整的全书收束答案。",
  "unit_contributions": [
    {
      "unit_id": "unit-one",
      "contribution": "这一单元为总问题贡献了什么。"
    }
  ],
  "boundaries": [
    "重要边界、争议或作者留下的未解决问题。"
  ]
}
```

It must contain every learning unit exactly once. Review it against the
authoritative complete source using the same review schema as a unit, with:

```json
{
  "artifact_type": "book_synthesis",
  "artifact_sha256": "<canonical normalized synthesis hash>",
  "source_text_sha256": "<whole source file sha256>"
}
```

Finalize:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  finalize <course-dir> \
  --synthesis <synthesis.json> \
  --review <review.json> \
  --expected-revision <revision>
```

## Correction

When a reviewed answer is later found wrong:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  invalidate-unit <course-dir> \
  --unit <unit-id> \
  --reason "具体错误及其影响" \
  --expected-revision <revision>
```

The runtime archives that unit and every later prepared unit under:

```text
<course-dir>/.book-grilling/history/
```

It then locks and clears the affected live versions. Re-extract, rebuild,
independently review, and prepare the invalid unit.

Affected prefetch caches are moved to `.book-grilling/history/prefetch/` rather
than silently reused.

## Audit and render

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  audit <course-dir>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  render <course-dir>
```

Audit verifies source fingerprint, immutable review hashes, unit state, current
target, and final synthesis presence. Render is for recovery or manual view
regeneration, never for routine turns.

## Public-reader privacy

The standalone page embeds only a derived public snapshot:

- completed and current answers;
- exact evidence for completed/current nodes;
- questions and status for locked nodes;
- no locked answers;
- no coverage ledger;
- no reviewer internals, hashes, event history, or course filesystem paths.
