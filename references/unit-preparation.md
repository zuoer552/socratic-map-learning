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
4. Select 2–6 short decisive excerpts. A packet may contain 1–12.
5. For each excerpt, record how it connects to the current claim, cause,
   method, interpretation, or boundary and, when useful, one plain-language
   bridge, term, or question seed.
6. Save the temporary JSON packet and call `prepare-unit`.
7. Keep the returned full packet and receipt in conversation context. Routine
   turns reuse them without new source reads.

## Packet schema

```json
{
  "current_node_id": "node-current",
  "unit_title": "本单元标题",
  "source_sha256": "optional-authoritative-source-fingerprint",
  "excerpts": [
    {
      "id": "excerpt-1",
      "text": "一至三句准确原文。",
      "translation": "只在确有需要时提供。",
      "connection": "这段话支持哪一个主张、原因、方法、解释或区分。",
      "term": "本单元至多一个必要术语。",
      "question_seed": "可由已有材料推出的一个小问题。",
      "locator": "仅供内部核验，不在日常回复显示。"
    }
  ]
}
```

The runtime fills `version`, `status`, `prepared_at`, and the authoritative
source fingerprint. A supplied fingerprint must match.

## Selection rules

- Accuracy outranks variety. Reusing one decisive passage is better than
  searching for a new decorative quote every turn.
- Excerpts must directly establish, distinguish, contextualize, support, limit,
  object, or reply within the current reading mode.
- Do not fill the packet with broad background that will not affect a question.
- Keep source text separate from translation, reconstruction, and teaching
  explanation.
- If the packet is insufficient, do one narrow refresh and replace the packet;
  do not scan the whole book.

## Boundary turn

If a mastered answer advances the current node, the same turn may:

1. commit the old unit;
2. prepare the new unit;
3. give the new source-grounded transition question.

That extra work is allowed only at the boundary. Later turns return to the
one-call fast path.
