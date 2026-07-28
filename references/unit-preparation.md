# Unit Preparation

Use this reference only at course start, after the current node changes, when a
prepared packet is missing or stale, or when a learner asks a source question
the packet cannot answer.

## Goal

Pay the source-reading cost once per learning unit. Prepare enough evidence for
several short Socratic turns without stuffing the entire book into context.

## Procedure

1. Run `context` only if no fresh receipt is available.
2. Read the current node, prerequisites, relevant reasoning relation, confusion
   notes, work mode, and source anchor.
3. Inspect only the smallest source range needed to teach that unit. Prefer an
   existing extracted text layer; render PDF pages only when the text layer is
   unusable or layout itself matters.
4. Select 2–6 shortest-sufficient decisive excerpts. A packet may contain
   1–12. Preserve the complete sentence or local context separately when the
   teaching excerpt is a fragment.
5. For each excerpt, record how it connects to the current claim, cause,
   method, interpretation, or boundary. The connection note must distinguish
   what the teacher must supply from what the learner can infer, and name any
   scope boundary that affects the next question.
6. Draft one candidate learner move with an expected answer and an explicit
   list of required premises. Treat it as a candidate, not executable
   instruction. Check that every premise was supplied, the move has a clear
   referent and one cognitive action, it does not repeat its own answer, source
   scope is preserved, and it advances one abstraction rung.
7. If no learner move is already open, select one candidate as `active_move`.
   Its `target_id` must name a real node, semantic edge, or inference step.
   Preparing a packet may never replace or reset an open or repair move.
8. Save the temporary JSON packet and call `prepare-unit`.
9. Verify that the HTML shows the active prompt but not its expected answer.
10. Keep the returned full packet and receipt in conversation context. Routine
   turns reuse them without new source reads.

## Packet schema

```json
{
  "current_node_id": "node-current",
  "unit_title": "本单元标题",
  "source_sha256": "optional-authoritative-source-fingerprint",
  "active_move": {
    "id": "move-current-connection",
    "node_id": "node-current",
    "target_id": "inference-current-connection",
    "interaction_kind": "fill",
    "prompt": "只补全这一根连接：……",
    "expected_answer": "供教师判断的规范化关系，不在学习页面显示。",
    "required_premises": [
      "此前已经提供的前提一",
      "此前已经提供的前提二"
    ],
    "scope_boundary": "这一回答不能进一步推出什么。"
  },
  "excerpts": [
    {
      "id": "excerpt-1",
      "text": "对话中使用的最短充分准确原文。",
      "full_text": "完整句子或必要的上下文。",
      "translation": "忠实直译；不是教师解释。",
      "connection": "这段话支持什么；老师必须先讲什么；学习者已有何前提；边界在哪里。",
      "term": "本单元至多一个必要术语。",
      "question_seed": "候选学习动作，不一定是开放问题。",
      "interaction_kind": "distinguish",
      "expected_answer": "一个明确、可共同判断的预期答案。",
      "required_premises": [
        "此前已经提供的前提一",
        "此前已经提供的前提二"
      ],
      "scope_boundary": "这一连接不能推出什么。",
      "locator": "仅供内部核验，不在日常回复显示。"
    }
  ]
}
```

The runtime fills `version`, `status`, `prepared_at`, and the authoritative
source fingerprint. A supplied fingerprint must match. `active_move` is
optional only when a move is already open or the turn is preparing source
before choosing one. Once selected, its expected answer and required premises
remain teacher-only runtime data.

## Selection rules

- Accuracy outranks variety. Reusing one decisive passage is better than
  searching for a new decorative quote every turn.
- `text` is the shortest sufficient teaching span; `full_text` preserves the
  complete source context when different. Mark every omission honestly.
- Excerpts must directly establish, distinguish, contextualize, support, limit,
  object, or reply within the current reading mode.
- Do not fill the packet with broad background that will not affect a question.
- Keep source text separate from translation, reconstruction, and teaching
  explanation.
- A `question_seed` is never authoritative. Re-evaluate it against the
  learner's latest reasoning and the response contract before use. Prefer a
  bounded distinction, completion, reconstruction, or judgment when an open
  question would be vague.
- Reject a seed when `expected_answer` is unclear, any `required_premises` item
  has not been supplied, the answer merely paraphrases the prompt, or the claim
  exceeds `scope_boundary`.
- Do not select a new `active_move` while the previous move is open or in
  repair. Resolve it first; source refresh never grants permission to change
  the intellectual target.
- If the packet is insufficient, do one narrow refresh and replace the packet;
  do not scan the whole book.

## Boundary turn

If a mastered answer advances the current node, the same turn may:

1. commit the old unit;
2. prepare the new unit;
3. give the new source-grounded transition question.

That extra work is allowed only at the boundary. Later turns return to the
one-call fast path.
