# Source-grounded learning-system model

Read this when initializing, entering a new problem, extending, restructuring,
migrating, or debugging a course.

## Canonical artifacts

1. authoritative source and fingerprint;
2. reviewed course blueprint;
3. SQLite learner state;
4. `argument_atlas.source_structure`;
5. `argument_atlas.system_spine`;
6. local reasoning maps and relation steps;
7. live snapshot;
8. deterministic standalone HTML.

The HTML is never authoritative.

## Independent layers

| Layer | Core fields | Governing question |
|---|---|---|
| Source | anchors, edition, fingerprint | What constrains this interpretation? |
| Source unit | parent, position, kind, title | Where does the work develop it? |
| System stage | question, answer, local map, arc | What problem is being solved? |
| System transition | previous stage, next stage, bridge | Why must the next problem be asked? |
| Reviewable node | complete statement and evidence | What is being established, explained, interpreted, or used? |
| Local relation | grounds, target, bridge, kind | How do these source-grounded elements connect? |
| Route | current target, allowed next | What should be learned next? |
| Learning cycle | phase, active move, evidence, weakest unresolved relation | What kind of learner move is useful now? |
| View | source route, question page, disclosure | How is the system displayed? |

No field from one layer substitutes for another.

## Minimal initialization

Initialization contains:

- source identity and fingerprint;
- the work's top-level source units and relevant nested units;
- terminal mastery goal;
- 5–16 governing questions;
- contiguous explanatory arcs;
- one bridge between every consecutive question;
- one source-reviewed current local map;
- exactly one learner target;
- one open learning frontier.

Future stages have a question and future map only. They contain no answer,
node, or relation data.

## Canonical source structure

```json
{
  "version": 1,
  "label": "原书结构",
  "unit_term": "卷／章／节",
  "work_mode": "theory",
  "units": [
    {
      "id": "unit-introduction",
      "position": 1,
      "parent_id": "",
      "kind": "introduction",
      "title": "导言",
      "summary": "这一单元在整部作品中做什么。",
      "source_refs": ["source-introduction"]
    }
  ]
}
```

Every system stage adds:

```json
{
  "primary_unit_id": "unit-introduction",
  "related_unit_ids": ["unit-preface"]
}
```

Source-structure invariants:

1. Unit ids are unique and stable.
2. Sibling positions are positive and unique under the same parent.
3. Parent links exist and contain no cycle.
4. Every stage has exactly one primary source unit.
5. A stage may name several related units, but may not repeat its primary unit.
6. One stage remains one canonical question page even when several units
   discuss it.
7. Source sequence never substitutes for a `must_ask` bridge.
8. `work_mode` is one of theory, history, practical, literature, or mixed.

## Canonical system spine

```json
{
  "version": 1,
  "title": "全书问题推进",
  "summary": "一个阶段的答案怎样迫使整部作品继续追问。",
  "terminal_mastery": "学习者能够复原答案、根据、后续问题与边界。",
  "arcs": [
    {
      "id": "arc-one",
      "position": 1,
      "title": "第一解释任务",
      "summary": "这一组问题共同解决什么。",
      "stage_ids": ["stage-a", "stage-b"]
    }
  ],
  "stages": [
    {
      "id": "stage-a",
      "position": 1,
      "arc_id": "arc-one",
      "question": "这里必须解决什么问题？",
      "map_id": "map-a",
      "answer_id": "claim-a",
      "primary_unit_id": "unit-introduction",
      "related_unit_ids": [],
      "source_refs": ["source-a"],
      "origin": "reviewed"
    }
  ],
  "transitions": [
    {
      "id": "transition-a-b",
      "from_stage_id": "stage-a",
      "to_stage_id": "stage-b",
      "relation": "must_ask",
      "label": "因此必须追问",
      "bridge": "为什么 A 使 B 成为不可回避的问题。",
      "source_refs": ["source-a", "source-b"],
      "origin": "reviewed"
    }
  ]
}
```

## System-spine invariants

1. Stage positions are contiguous from 1.
2. Every stage belongs to exactly one arc.
3. Arc coverage includes every stage exactly once.
4. Every reviewed stage's `answer_id` equals its local map target.
5. Every future stage has an empty `answer_id`.
6. Every consecutive stage pair has one transition, in order.
7. Every transition has relation `must_ask`, label `因此必须追问`, a bridge,
   source anchors, and provenance.
8. A bridge describes explanatory, causal, practical, or interpretive pressure,
   not chapter order.
9. A canonical answer node appears in one system stage only.

## Work-mode routing

Choose the grammar of the current unit before compiling its local map:

| Mode | Target | Grounds or relations | Typical critical checks |
|---|---|---|---|
| theory | claim or conclusion | premises, definitions, inference, objection, reply | validity, hidden premise, scope |
| history | outcome or interpretation | context, chronology, causes, evidence, rival accounts | source quality, causal weight, omission, anachronism |
| practical | intended result or guidance | goal, method, condition, action, evidence, failure mode | feasibility, precondition, side effect, transfer boundary |
| literature | interpretation | voice, character, conflict, form, textual evidence, alternative reading | textual warrant, form, ambiguity, rival reading |
| mixed | the current unit's target | one explicitly selected mode, changed only when the source changes task | whether modes were silently conflated |

Do not convert chronology into deduction, a method into a universal law, or a
literary interpretation into a factual proposition merely to fit the storage
schema.

## Canonical reviewable node

The runtime stores these nodes in proposition fields for compatibility. A node
remains meaningful without the conversation and can be judged source-supported,
plausible, effective, or textually warranted as appropriate to its mode.
Required fields include:

- stable id;
- source module;
- complete statement in `title`;
- summary and plain explanation;
- mastery criterion;
- source anchors;
- common confusions;
- lesson-route fields.

Questions may remain as legacy lesson-route nodes but cannot appear inside a
local reasoning map.

## Canonical reasoning atlas

```json
{
  "version": 1,
  "default_map_id": "map-current",
  "system_spine": {},
  "maps": [
    {
      "id": "map-current",
      "kind": "argument",
      "parent_id": "",
      "entry_node_id": "",
      "title": "论证名称",
      "question": "这张局部图回答什么？",
      "summary": "怎样回答。",
      "position": 1,
      "status": "current",
      "conclusion_id": "claim-c",
      "node_ids": ["claim-a", "claim-b", "claim-c"],
      "source_refs": ["source-a"],
      "origin": "reviewed"
    }
  ],
  "inferences": [
    {
      "id": "inference-a-b-c",
      "map_id": "map-current",
      "premise_ids": ["claim-a", "claim-b"],
      "conclusion_id": "claim-c",
      "bridge": "A 与 B 共同成立时，C 才能推出。",
      "kind": "supports",
      "source_refs": ["source-a"],
      "mastery_edge_ids": [],
      "origin": "reviewed"
    }
  ]
}
```

`argument_atlas`, `premise_ids`, `conclusion_id`, and `inferences` are stable
runtime field names. Their learner-facing meaning is determined by
`source_structure.work_mode`.

Map kinds:

- `book` — a work-level map using several established stage answers;
- `argument` — one focused local map. The name is retained for compatibility
  even when the unit is causal, practical, or interpretive.

Inference kinds:

- `supports`;
- `objects`;
- `responds`;
- `limits`.

The four inference kinds encode structural roles, not genre:

- history may store evidence or causes as `supports`, a rival account as
  `objects`, an answer to it as `responds`, and uncertainty as `limits`;
- practical works may store methods and conditions as `supports`, a failure
  mode as `objects`, mitigation as `responds`, and applicability as `limits`;
- literature may store textual evidence as `supports`, an alternative reading
  as `objects`, an interpretive answer as `responds`, and ambiguity as
  `limits`.

## Local-map invariants

1. `conclusion_id` belongs to `node_ids`.
2. Every visible node is a non-question, reviewable statement appropriate to
   the current work mode.
3. Every stored relation has grounds, one target, a complete bridge, source,
   and origin.
4. Every premise and conclusion belongs to the inference's stored map.
5. Following incoming inferences from the final conclusion reaches every
   stored visible node.
6. Future maps contain no conclusion, nodes, or inferences.
7. A child map's `entry_node_id` belongs to its parent.
8. A visible child conclusion equals its parent entry proposition.
9. Every visible root-to-child path contains at most 12 unique nodes.
10. Multiple grounds that jointly establish a target share one relation step.
11. One inference bridge performs one reviewable relation move. If a bridge
    hides several inferential, causal, practical, or interpretive jumps, split
    it into atomic steps.
12. The target node's summary is the compact conclusion; its incoming
    inferences are the expandable reconstruction. The summary may not replace
    the relation chain.
13. When the active lesson-route node is a reviewed current map's conclusion,
    propositions newly compiled into that map are visible even when their
    legacy route status remains `future`. That status means the proposition
    has not become a route target; it does not hide the active conclusion's
    reviewed grounds. Before the learner reaches the conclusion, and in every
    future map, answers remain hidden.

Stored maps may reuse established node ids. The renderer shows only the selected
question's local map and can name an earlier answer inside its relation bridge
instead of creating another question page.

## Just-in-time compilation

Before teaching a problem:

1. review the relevant source span;
2. identify the current unit's `work_mode` and use its grammar;
3. state the governing question;
4. draft the final answer as one reviewable node;
5. identify direct and recursive grounds appropriate to the mode;
6. group jointly necessary grounds without inventing necessity;
7. write one complete, speakable bridge per relation;
8. add only decisive objections, rival accounts, failure modes, alternatives,
   replies, or boundaries;
9. determine why this answer forces the next governing question;
10. write the `must_ask` transition;
11. attach source anchors and provenance;
12. move definitions, examples, quotations, and analogies to detail;
13. split oversized local maps;
14. validate local reachability and global stage continuity;
15. expose only the reviewed frontier.

## Learner evidence

Node diagnoses (runtime name: proposition diagnoses):

- mastered;
- partial;
- misconception;
- unknown.

Evidence kinds:

- own_words_reason;
- correct_distinction;
- correct_transfer;
- none.

Relation mastery (runtime name: inference mastery):

- unassessed;
- understood;
- reconstructable;
- transferable;
- retained.

A node is not robustly mastered because its sentence was repeated. The learner
must reconstruct its incoming source-grounded relation and the outgoing
`must_ask` transition.

One resolved micro-connection may raise its relation to `understood` while the
containing node remains `partial`. Node diagnosis and relation mastery are
different layers; neither may erase the other.

Local learning-cycle phases:

- understanding;
- verification;
- critical;
- transfer;
- synthesis.

The phase is learner-state metadata, not source topology. It never proves a
relation or changes the canonical question chain. A new unit begins at
`understanding`; a completed unit closes at `synthesis`. Transfer may be skipped
when no source-faithful, relevant case exists.

### Active learner move

The runtime keeps exactly one optional `active_move`:

```json
{
  "id": "move-current-link",
  "node_id": "node-current",
  "target_id": "inference-current-link",
  "interaction_kind": "fill",
  "prompt": "只补全这一根连接：……",
  "expected_answer": "教师内部使用的规范关系。",
  "required_premises": ["已经提供的前提"],
  "scope_boundary": "不能从这一步推出什么。",
  "status": "open",
  "attempts": []
}
```

`target_id` names a real node, semantic edge, or inference. `expected_answer`,
required premises, learner responses, and attempts are teacher-only data. The
public map receives only the prompt, target, status, and current missing link.

The only active statuses are:

- `open` — the learner has not yet attempted or the answer is awaiting review;
- `repair` — accepted parts are preserved, but one named connection remains
  unresolved.

Resolution moves the full record to `move_history` with the learner's attempts,
accepted parts, and one canonical `resolved_statement`. A resolved record is
history, not an active status.

`repair` is a substate inside the current learning-cycle phase, never a sixth
phase. While a move is open or in repair, route, target, phase, and mastery are
frozen. A source refresh may enrich the explanation but cannot replace the
move. Prompt and explanation defects create no learner evidence.

A turn update uses exactly one of these outcomes:

- `resolved` — record `resolved_statement`; a next move may be opened;
- `partial`, `misconception`, or `unknown` — record one `missing_link`; keep
  the same move in repair;
- `prompt_defect` or `explanation_defect` — record the defect as the missing
  link, force evidence kind `none`, and repair the teaching design.

Keep unit packets by current node rather than discarding them at the next unit.
The active chat may use the shortest sufficient excerpt, while the map can
progressively disclose the stored full source context and faithful translation.

## Transaction model

Every context receipt contains revision and the current node id (stored in the
legacy proposition field).

A routine commit:

1. checks the receipt;
2. resolves or repairs the active move before any target change;
3. preserves attempts, accepted parts, the missing link, and the normalized
   resolution;
4. stores learner evidence only when the turn actually supplies it;
5. optionally raises the resolved relation's mastery level;
6. optionally updates phase or route only after resolution;
7. optionally opens exactly one next move;
8. records the most recently demonstrated relation;
9. runs cheap invariants;
10. regenerates state output and installs the derived HTML.

Routine commits do not mutate the system spine or local-map topology.

## Reviewed structural change

Use `structure` when:

- the source hierarchy or a stage-to-source assignment is missing;
- a table-of-contents item was incorrectly treated as a logical transition;
- a stage answer or `must_ask` bridge is missing;
- a question was incorrectly made a reviewable node;
- a binary relation fakes joint sufficiency or conflates distinct causes,
  evidence, or conditions;
- a relation lacks a bridge, source, or provenance;
- a node does not contribute to its target;
- a canonical stage answer is duplicated;
- a local map needs a rival account, failure mode, alternative, reply, boundary,
  or child map;
- a future answer was exposed.

Create a database backup, preserve evidence, validate, render, and then commit
the structural revision.

## Performance contract

Routine turns reuse the previous receipt and current relation context. They do
not reread the whole source, rebuild the system, run deep validation, regenerate
source structure, invoke browser acceptance, or repackage the Skill.

Only a reviewed topology revision changes source assignments or local-map
structure.
