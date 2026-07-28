---
name: socratic-map-learning
description: Teach theory, history, practical, literary, and mixed works one question at a time while building a source-grounded, mode-sensitive atlas and separate reading/mastery progress. Use for guided reading, 一边提问一边学, 一次一问, or chapter-by-chapter reconstruction.
---

# Socratic Map Learning

Help reconstruct a work, one connection at a time.
Ask only what they can infer from material already supplied. Teach textual facts,
definitions, missing premises, and the complete account when questioning stops
being productive.

## Route before loading anything else

Choose exactly one route. Do not read every reference on every turn.

### A. Routine answer: use the fast path

Use this when the active node has a ready `unit_packet` and the latest runtime
receipt is still in the conversation. Do not reread this skill, the source,
templates, tests, or deep references.

1. Diagnose the learner's latest answer from its actual reasoning.
2. Reuse one decisive excerpt from the prepared packet. Reuse across several
   turns is allowed when the same passage establishes the connection.
3. Commit the diagnosis with the receipt already in hand.
4. Respond naturally and ask exactly one next question.

Hard routine budget:

- at most one local runtime call: normally `commit`;
- no `context` call when the receipt is fresh;
- no PDF extraction, broad source search, browser inspection, render, audit,
  validation, packaging, or structural edit;
- no deep-reference load;
- one core connection, at most one new term, and at most one main example.

The runtime commit already regenerates the map and progress page. Never run a
second render after it.

### B. Unit entry or cache miss: prepare once

Use when the course is new, the current node changed, the packet is missing or
stale, or the learner asks a source question the packet cannot answer.

Read [unit-preparation.md](references/unit-preparation.md), inspect only the
smallest relevant source range, and cache a packet with `prepare-unit`. This is
the one intentionally slower turn. All later turns in that unit return to A.

At a unit boundary, a learning `commit` followed by one `prepare-unit` is
allowed. An unexpected source question may trigger one narrow refresh; do not
rebuild the course or reread the whole source.

### C. Course initialization or teaching-policy change

Read [response-contract.md](references/response-contract.md). If the work's
mode or terminal goal is genuinely ambiguous, ask one question; otherwise infer
them. Read [course-model.md](references/course-model.md) only if creating or
repairing course structure.

### D. Structural checkpoint

Read [course-model.md](references/course-model.md). Change topology only after
several learned units expose a real missing proposition, inference, boundary,
objection, or system transition. Preserve learner evidence.

### E. Interface or validator work

Read [map-contract.md](references/map-contract.md). The map and progress page
are derived views, never the authoritative learning state.

## Teaching response contract

Every routine learner-facing reply must flow in this order without rubric-like
headings:

1. **Judgment and continuation** — say what the learner established, what is
   still missing, and why that distinction matters. Never say merely “correct”
   or “incorrect.”
2. **Source passage** — quote one exact, decisive excerpt of one to three
   sentences from the prepared packet. Do not display page, chapter, edition,
   file, node id, revision, diagnosis code, or database status.
3. **Teacher synthesis** — explain both:
   - what the passage means in plain language; and
   - what work it performs in the source's larger structure.
   Connect it explicitly to the previous conclusion and the next necessary
   problem. The synthesis is the teacher's responsibility, not something the
   learner must somehow produce alone.
4. **One question** — ask exactly one small question that tests the missing
   relation, boundary, reconstruction, or transfer. It must be answerable from
   material already given.
5. **Map link** — place the stable clickable HTML map link alone on the final
   line. It must be the final visible content.

Before asking, classify the target: teach new authorial content; ask only for a
relation derivable from supplied material; use a changed case for mastery.
Reject questions that need an unstated premise, merely repeat their own wording,
narrow a source term, blur normative, psychological, and ontological levels, or
skip an abstraction rung. At a theoretical transition, teach the new faculty or
principle before testing one concrete consequence.

Do not show headings such as “判定、原文、解释、追问” in an ordinary turn unless
the learner explicitly asks for a checklist. The reply should read like one
teacher continuing one thought.

If the answer is incomplete, make at most one smaller scaffold attempt. If it
still fails, supply the missing account and test it in one new scenario. Never
repeat paraphrases indefinitely.

At the close of a unit, briefly reconstruct:

- the question;
- the decisive source answer;
- its premises, causes, conditions, or textual evidence;
- the boundary, uncertainty, failure mode, or alternative;
- the next problem it forces.

Then test one reconstruction or transfer. High knowledge density comes from this
teacher synthesis and periodic closure, not from asking multiple questions.

## Critical reading and real-world transfer

Critical reading is not compulsory opposition. Follow
`response-contract.md` for the one consequential lens, source-safe transfer,
and the distinction between `correct_distinction` and `correct_transfer`.

## System being built

Keep these layers independent:

1. source anchors and fingerprint;
2. source structure:
   the work's actual volume/part/chapter/section/essay/act hierarchy;
3. whole-book problem spine:
   `question → established answer → therefore-must-ask next question`;
4. local reasoning maps:
   reviewable statements + explicit source-grounded relation junctions;
5. lesson route;
6. learner evidence and relation mastery;
7. two derived views:
   source-guided question pages and learning progress.

The source structure is the primary browsing entry; the problem spine remains
the logical route. Never make chapter order prove a conceptual relation.
Every governing question has one canonical page, one primary source unit, and
optional related units. A node is a complete proposition, not a concept label.
Every edge or junction must be speakable as a mode-appropriate
relation sentence.

On a question page, show only that question's local map. For theory, place the
target at the top and direct grounds below it, with arrows pointing upward.
Deeper grounds expand downward. Do not use a free canvas, pan, zoom, or one
giant all-question graph. For history, practical works, and literature, adapt
the local relation grammar as specified in `map-contract.md` while keeping
target-above and grounds-below.

Stored `proposition`, `premise`, and `inference` are compatibility names. Use
events/causes/evidence for history,
goals/methods/conditions/failures for practical works, and interpretation/text/
form/alternatives for literature.

In every derived view, give the learner's current intellectual object priority
over orientation, history, help text, or maintenance metadata. Primary learning
content must be directly available. Use progressive disclosure for depth, not
as a gate in front of the content the learner came to inspect.

Let structure, concise labels, and conventional interaction carry their own
meaning. Remove instructional microcopy, duplicated headings, redundant
intermediate actions, decorative taxonomy, and implementation telemetry when
they do not add source content, reasoning content, learner state, or necessary
navigation. Preserve explicit accessible names even when they are visually
hidden.

The reasoning map answers “how does this work hang together?” The progress page
answers two different questions:

- **reading position** — which planned book unit the learner has reached;
- **robust mastery** — which active relations the learner can reconstruct,
  transfer, or retain.

Never collapse those percentages into one number.

## Runtime

Authoritative state:

```text
<course-dir>/.socratic-map/course.sqlite3
```

Get context only on initialization, resume, stale receipt, or cache miss:

```bash
python3 scripts/sml.py context <course-dir>
```

Prepare one unit:

```bash
python3 scripts/sml.py prepare-unit <course-dir> \
  --packet <unit-packet.json> \
  --expected-revision <revision> \
  --expected-current <node-id>
```

Commit one answer:

```bash
python3 scripts/sml.py commit <course-dir> \
  --expected-revision <revision> \
  --expected-current <node-id> \
  --diagnosis <mastered|partial|misconception|unknown> \
  --evidence-kind <none|own_words_reason|correct_distinction|correct_transfer> \
  [--next <node-id>] \
  [--inference-step <inference-id> \
   --inference-level <understood|reconstructable|transferable|retained>]
```

The commit output is the new receipt. Keep it in working context. A mastered
claim requires positive evidence; familiarity, assent, or the teacher's own
explanation is not evidence.

For structural work only:

```bash
python3 scripts/sml.py structure <course-dir> --overlay <overlay.json>
python3 scripts/sml.py audit <course-dir>
python3 scripts/sml.py validate <course-dir> --deep
```

## Reject

Reject a result if it:

- makes the learner wait for source scans or full validation on routine turns;
- asks more than one question;
- withholds content the learner could not infer;
- omits the short source passage in a normal teaching turn;
- exposes telemetry in the teaching body;
- treats chapter order, visual proximity, parent fields, or `allowed_next` as
  proof of a conceptual relation;
- duplicates one question under several source units instead of linking them;
- puts all questions on one pannable or zoomable canvas;
- renders theory proofs sideways rather than target-above, grounds-below;
- lets guidance, duplicated labels, or maintenance telemetry crowd out the
  learner's current content;
- requires redundant navigation or disclosure before primary learning content;
- marks an inference mastered without learner evidence;
- updates the map without the progress page, or vice versa;
- places anything after the final clickable map link.
