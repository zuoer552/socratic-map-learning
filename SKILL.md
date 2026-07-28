---
name: socratic-map-learning
description: Teach theory, history, practical, literary, and mixed works one meaningful learner move at a time while building a source-grounded, mode-sensitive atlas and separate reading/mastery progress. Use for guided reading, 一边提问一边学, 一次一问, or chapter-by-chapter reconstruction.
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

1. Close or repair the exact active learner move from the learner's actual
   reasoning.
2. Reuse one decisive excerpt from the prepared packet. Reuse across several
   turns is allowed when the same passage establishes the connection.
3. Commit its normalized resolution or repair state with the receipt already
   in hand.
4. Respond naturally. Open a new target only after closure, and end with
   exactly one useful learner move.

Hard routine budget:

- at most one local runtime call: normally `commit`;
- no `context` call when the receipt is fresh;
- no PDF extraction, broad source search, browser inspection, render, audit,
  validation, packaging, or structural edit;
- no deep-reference load;
- one core connection, two to five atomic reasoning steps, at most one new
  term, and at most one main example.

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

[response-contract.md](references/response-contract.md) is the canonical
learner-facing policy. Enforce these state rules before applying its prose
shape:

1. An active move must be either resolved or placed in repair before the reply
   can continue.
2. A resolved reply states one normalized resolution near the top. It preserves
   the intended relation but does not demand one exact wording.
3. A partial answer preserves accepted parts and names one missing connection.
   A misconception repairs the same target. An unknown answer first triggers a
   prompt-and-explanation audit.
4. While a move is open or in repair, do not change target, node, phase, or
   mastery. Repair is a substate inside the current five-phase cycle, not a
   sixth phase.
5. Atomicity is learner-relative. Two to five displayed steps are a
   presentation cap; split any step the learner cannot reconstruct.
6. After closure, and only then, open exactly one eligible learner move.

The normal visible order is:
`resolution or repair → source identity → expanded connection → compact
synthesis → one learner move → map link`. Keep the map link alone on the final
line. Do not expose expected answers, internal ids, revisions, diagnoses, or
runtime state.

## Five-phase learning cycle

Run one local learning unit through a coherent cycle:

1. **understanding** — source, faithful translation when needed, atomic
   reconstruction, local route, compact synthesis;
2. **verification** — test the weakest supplied relation with one bounded
   learner move;
3. **critical** — inspect the single most consequential premise, evidence
   strength, inference, omission, feasibility issue, textual warrant, or
   boundary appropriate to the work mode;
4. **transfer** — after two or three connected conclusions, map the source
   relation to one genuinely relevant case and state the disanalogy; skip this
   phase when no high-quality case exists;
5. **synthesis** — reconstruct the local unit, distinguish what the learner
   established from what the teacher supplied, and preserve remaining review
   items.

The cycle is mandatory at the local-unit level, not as five sections in every
reply. Keep chat natural. Store and display the active phase in the map.
Transitions depend on evidence, not turn count. Immediate prompted recall may
establish `understood`; independent reconstruction, appropriate transfer, and
later retrieval establish stronger levels.

An unresolved move freezes the current phase. Its repair substate never counts
as phase progress.

## Critical reading and real-world transfer

Critical reading is not compulsory opposition. Transfer is not compulsory
novelty. Follow `response-contract.md` for the one consequential critical lens,
domain-neutral relevance and safety checks, the complete transfer mapping, and
the distinction between `correct_distinction` and `correct_transfer`.

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
6. active learner move, closure history, learner evidence, relation mastery,
   and current learning-cycle phase;
7. a compact conclusion plus an expandable atomic relation chain;
8. two derived views:
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

On the map, show the compact conclusion by default and keep the atomic chain,
full source context, critical boundary, transfer record, and per-relation
mastery progressively available. Highlight the most recently demonstrated
relation rather than coloring a whole unit as understood.

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
  --turn <turn-update.json> \
  [--learning-phase <understanding|verification|critical|transfer|synthesis>] \
  [--next <node-id>] \
  [--inference-step <inference-id> \
   --inference-level <understood|reconstructable|transferable|retained>]
```

`turn-update.json` closes or repairs the current move and may open the next one
only when the current outcome is `resolved`. The runtime rejects advancement,
phase change, or mastery increase while a move remains unresolved. The commit
output is the new receipt. Keep it in working context. A mastered claim
requires positive evidence; familiarity, assent, a defective prompt, or the
teacher's own explanation is not evidence.

For structural work only:

```bash
python3 scripts/sml.py structure <course-dir> --overlay <overlay.json>
python3 scripts/sml.py audit <course-dir>
python3 scripts/sml.py validate <course-dir> --deep
```

## Reject

Reject a result if it:

- makes the learner wait for source scans or full validation on routine turns;
- requires more than one learner move;
- forces an open question when a clearer bounded learner action is available;
- records failure on an ambiguous or premise-incomplete prompt as learner
  evidence;
- withholds content the learner could not infer;
- omits source identity, atomic reconstruction, compact synthesis, or the local
  route in a normal teaching turn;
- presents teacher synthesis as source wording;
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
