# Source and learning-unit preparation

Read this only when starting a new book or repairing its source manifest.

## Goal

Create a complete source navigation and a conservative sequence of learning
units. Do not build knowledge trees during this step.

## Source gate

Require:

- complete authoritative text;
- title and author;
- exact edition or translation;
- stable local file;
- complete contents or another recoverable source hierarchy.

If only part of a work is available, title the course as partial, include only
available source units, and never report the whole work complete.

Do not initialize from reviews, abstracts, summaries, model memory, or an
unverified online transcription.

## Safe source budget

A learning unit is the largest coherent source block that can be read in full
while leaving ample space for instructions, existing context, the generated
tree, source comparison, and the reply.

1. If the usable model context is reliably known, let exact source text occupy
   no more than 20% of it.
2. Otherwise default to at most 8,000 estimated source tokens.
3. Reduce the limit for OCR noise, tables, parallel translations, dense
   notation, or interpretively difficult prose.
4. Never use the advertised maximum context as the source limit.

Estimate before semantic reading. The estimate may be approximate, but every
unit must declare the method and stay below the chosen limit.

## Splitting

Prefer boundaries in this order:

1. the author's chapter, lecture, essay, scene, or numbered unit;
2. the author's section or subheading;
3. a complete argument, topic sequence, or paragraph group;
4. a paragraph boundary as a last resort.

Never cut inside a sentence, quotation, proof step, table row, or tightly bound
argument. When a system split is necessary:

- keep it under the original source parent;
- label it visibly as a learning-unit split;
- use titles such as `第三章 · 学习单元 1/3`;
- give it its own exact locator;
- preserve the preceding result needed to enter the next unit.

Do not mark overlapping ancestor and descendant ranges as separate learning
units.

## Source hierarchy

Keep one flat list with parent links. It may contain non-learning navigation
groups and learning units.

Every sibling group has positions `1..n`. Every learning unit has a unique
global sequence `1..n`. This sequence is the reading order.

Example:

```json
{
  "schema_version": 1,
  "book": {
    "id": "example-work",
    "title": "作品标题",
    "author": "作者",
    "edition": "出版社、年份、译者或版本标识",
    "language": "zh-CN"
  },
  "source": {
    "path": "/absolute/path/to/work.pdf",
    "kind": "pdf",
    "coverage_scope": "complete",
    "coverage_note": ""
  },
  "safe_context": {
    "source_token_limit": 8000,
    "method": "未知模型容量，采用默认 8000 token 上限"
  },
  "source_units": [
    {
      "id": "part-one",
      "parent_id": "",
      "position": 1,
      "kind": "部分",
      "title": "第一部分",
      "locator": "目录：第一部分",
      "learning_unit": false
    },
    {
      "id": "unit-one",
      "parent_id": "part-one",
      "position": 1,
      "kind": "章",
      "title": "第一章",
      "locator": "第一章，第 1–18 页",
      "learning_unit": true,
      "sequence": 1,
      "split_origin": "author",
      "estimated_tokens": 6200
    }
  ]
}
```

## Initialization audit

Before `init`, verify:

- the source opens and its fingerprint can be calculated;
- every visible contents item is represented;
- every learning-unit range is contiguous and non-overlapping;
- the complete available source belongs to a learning unit;
- system-created splits are labeled as such;
- no unit exceeds the safe source budget;
- reading sequence follows the author's source order.

Run:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  init <course-dir> \
  --manifest <manifest.json> \
  [--page <absolute-reader.html>]
```

The reader initializes immediately. Future units contain source navigation only.

`source.coverage_scope` is mandatory:

- use `complete` only when the identified edition is fully available;
- use `partial` when any part is unavailable, and state the exact available
  range or omission in `coverage_note`.

The reader keeps a partial-source warning visible and never labels that course
as a completed whole book.
