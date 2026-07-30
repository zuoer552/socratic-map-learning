---
name: book-grilling
description: Systematically teach a complete knowledge-oriented work one source-sized unit and one question at a time, giving a recommended answer while building a reviewed, progressively unlocked visual question tree. Use for 读书, 精读, 一次一问, 按章学习, guided reading, learning a whole nonfiction book, resuming a Book Grilling course, or reviewing completed unit knowledge trees.
---

# Book Grilling

Teach the whole work without turning the course into a learning-management
platform. The interaction follows `grilling`: walk one branch at a time, show
the recommended answer, resolve the learner's doubt, then continue.

Version 1 establishes systematic exposure and shared understanding. It does
not claim closed-book recall, retention, or mastery.

## Non-negotiable model

- Use only knowledge-oriented works with an accessible, edition-identified
  complete source. A partial source creates a visibly partial course.
- Preserve the author's volume/part/chapter/section/essay numbering and names.
- Split that structure into **learning units**: the largest coherent source
  blocks that fit safely in one preparation context.
- Build no whole-book knowledge graph. Build one reviewed question tree only
  when entering its learning unit.
- Every tree node is exactly:
  `one question + one recommended answer + exact source evidence`.
- Show one question and its recommended answer at a time. The learner may
  agree, ask, challenge, or request clarification.
- Resolve means the authorial position and its reason are clear. The learner
  may still disagree with the author.
- Unlock the next depth-first node only after the current node is resolved.
- Treat the standalone HTML as a derived reader. JSON is authoritative.

## Route each turn

### 1. Resume before reading

If `<course-dir>/.book-grilling/course.json` exists, run:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  context <course-dir>
```

Use the returned receipt. Do not reread the full source, rebuild a completed
tree, run a browser audit, or regenerate the page separately on a routine turn.

### 2. Initialize a book once

When no course exists, read
[source-preparation.md](references/source-preparation.md). Establish the exact
source, extract its complete source hierarchy, make a conservative learning-unit
manifest, then run `init`.

Initialization creates the book page and source navigation. Future units expose
only their source title and location.

### 3. Prepare one learning unit once

When context says `prepare_current_unit`, read
[unit-preparation.md](references/unit-preparation.md).

1. Extract the exact complete unit text.
2. Build the full unit question tree and source-coverage ledger.
3. Fingerprint the normalized tree and exact unit text.
4. Start a fresh independent reviewer. Give it only the exact unit text, tree,
   schemas, and review task—not the generator's reasoning or intended verdict.
5. Repair every issue and repeat review until it passes.
6. Install the exact reviewed tree with `prepare-unit`.

Never unlock a unit when the source is truncated, an excerpt is not exact, the
coverage ledger is incomplete, or independent review is unavailable.

### 4. Teach with the grilling loop

Read [teaching-loop.md](references/teaching-loop.md) when starting or repairing
a course's interaction policy.

For the current node:

1. State its question.
2. Give the complete recommended answer in ordinary language.
3. Explain only the relation necessary to make that answer clear.
4. Identify when the answer is direct source wording, editorial synthesis,
   external context, or a contested interpretation.
5. End with exactly one learner decision about this node.

If the learner has a doubt, answer it and commit `open`; remain on the same
node. When the account is clear, commit `resolved`. A commit atomically updates
the state, unlocks at most one node, and regenerates the page.

### 5. Cross a unit boundary

After the last node resolves, the runtime archives the completed tree and moves
to the next source unit. The next turn prepares that unit; it does not scan
ahead during the previous unit's routine conversation.

### 6. Close the whole work

When context says `prepare_book_synthesis`, create one reviewed final account:

- the work's governing question;
- the contribution of every completed learning unit;
- the final answer;
- its important boundaries, disputes, and unresolved questions.

Install it with `finalize`. This produces a linked synthesis page, not a
whole-book graph and not an examination.

## Runtime

Read [runtime-contract.md](references/runtime-contract.md) before constructing
manifest, tree, review, turn, or synthesis JSON.

In every command, replace `/absolute/path/to/book-grilling` with the absolute
directory containing this `SKILL.md`. Never look for the runtime inside the
book's course directory and never rely on the shell's current directory.

Normal commands:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  init <course-dir> --manifest <manifest.json>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  context <course-dir>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  fingerprint --text-file <unit.txt>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  fingerprint --json-file <tree.json>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prepare-unit <course-dir> \
  --tree <tree.json> --review <review.json> --source-text <unit.txt> \
  --expected-revision <revision> --expected-unit <unit-id>
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  commit <course-dir> \
  --turn <turn.json> --expected-revision <revision> \
  --expected-unit <unit-id> --expected-node <node-id>
```

The full command list is available through `--help`.
Use [examples/demo](examples/demo) only to debug schemas or render behavior;
do not load it during an ordinary book turn.

## Accuracy policy

- Never substitute a summary, review, table of contents, or model memory for
  the authoritative source.
- Never place a paraphrase inside quotation marks.
- Every displayed excerpt must be an exact substring of the prepared unit text.
- Distinguish source statement from teacher organization and external context.
- Independent review is a hard unlock gate, not decorative metadata.
- If a discovered error affects a learned unit, run `invalidate-unit`; do not
  silently patch its answer. The runtime archives and locks that unit and every
  later unit for reviewed repair.
- Say what is uncertain. Stop rather than guess.

## Performance policy

Routine turn:

- reuse the context receipt and prepared tree;
- at most one local runtime call;
- no source extraction, tree generation, independent review, deep audit, or
  browser check;
- do not call `render` after `commit`; commit already renders.

Slow work is allowed once at book initialization, once per unit preparation,
and once at final synthesis.

## Reader policy

The generated reader is a calm academic editorial interface:

- author source hierarchy in a desktop sidebar and mobile drawer;
- completed units fully reviewable;
- current unit progressively unlocked;
- locked answers absent from the embedded public payload;
- warm paper surfaces, teal completion, amber attention;
- responsive 375px through wide desktop, light/dark modes, visible focus,
  44px targets, semantic headings, keyboard access, reduced motion;
- no free canvas, panning, zoom controls, decorative telemetry, or external
  font/icon/network dependency.

## Reject

Reject a result that:

- starts teaching before the complete current unit is extracted and reviewed;
- asks several learner decisions at once;
- withholds the recommended answer and asks the learner to invent new content;
- advances while the learner still has an unresolved doubt;
- treats agreement with the author as required;
- creates a whole-book graph or a global node taxonomy;
- reveals locked answers in HTML, embedded JSON, or accessibility text;
- performs more than one state/render call on a routine turn;
- claims mastery, retention, or closed-book ability;
- places unreviewed or source-unsupported content in an unlocked node.
