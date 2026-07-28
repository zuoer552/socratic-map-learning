# Source-guided question-page contract

Read this only when changing the renderer, templates, progress page, structural
navigation, export, or interface validation.

## Purpose

The interface helps a learner answer three different questions without
confusing them:

1. Where am I in the work's actual source structure?
2. Which governing problem am I solving, and why does it follow from the
   previous problem?
3. What local source-grounded relations establish this problem's answer?

It is not a transcript, a giant mind-map canvas, or a generic network browser.

## Fixed information architecture

The primary route is:

```text
source contents
  → source-unit landing page
    → questions belonging primarily to that unit
      → one unique page for one governing question
```

The desktop left sidebar is collapsible. On mobile it becomes a drawer. It has
two tabs:

- source structure — the primary navigation;
- whole-book problem chain — a secondary logical index.

A source-unit page explains:

- what kind of unit it is;
- its role in the work;
- its child source units;
- the questions primarily assigned to it;
- reading completion for its descendant questions.

A question page contains:

- source-structure breadcrumbs;
- question, status, primary source unit, and related source units;
- only this question's local relation map, immediately after the question
  header;
- progressively disclosed source, explanation, inferential role, and mastery
  details;
- the question overview and broader source location after the local map;
- previous-question pressure and next necessary problem, below the local
  map.

Each governing question has exactly one canonical page. Related chapters link
to that page; they never create duplicates.

## Content economy

Visible interface copy must serve at least one of four functions:

1. source content or source location;
2. a question, reviewable statement, relation, objection, alternative, or
   boundary;
3. learner state or progress;
4. necessary navigation.

Remove copy that merely explains the page's own layout, repeats a nearby
heading, narrates an obvious interaction, exposes maintenance state, or adds a
redundant step before primary content. Empty states are short factual states,
not mini tutorials. Accessibility labels remain explicit and may be visually
hidden when a visible duplicate would add noise.

## Source structure is generic

Store the work's real hierarchy as `argument_atlas.source_structure`. Render
its own vocabulary:

- theory/nonfiction: volume, part, chapter, section, essay;
- history: period, part, chapter, episode;
- practical work: part, method, step, case;
- literature: part, act, scene, chapter, poem.

“Chapter” is not hard-coded as the universal unit. The generic object is a
source unit with a parent, sibling position, kind, title, summary, and sources.

Source order and problem logic are independent:

- source structure answers “where does the author discuss this?”;
- the problem spine answers “why must this question follow?”;
- the local relation map answers “how is this answer established?”.

## Local relation grammar

For theory mode, the local map is a proof and reads bottom to top:

```text
                 target or conclusion
                         ↑
               because-therefore bridge
                         ↑
               direct ground(s) below
                         ↑
             deeper grounds when expanded
```

The target is always at the top. Direct grounds are visible by default.
Recursive grounds sit lower and open through ordinary disclosure controls.
Jointly necessary premises share one visible inference bridge.

Do not use free coordinates, SVG graph layout, canvas panning, or zooming.
Local structure must remain readable as ordinary responsive HTML and vertical
page scrolling.

Other work modes keep “target above, grounds below” but adapt the local
relation:

- history: outcome/interpretation above; causes, evidence, and rival readings
  below;
- practical: intended result above; method, conditions, failure modes, and
  transfer evidence below;
- literature: interpretation above; textual evidence, form, conflict, and
  alternative readings below.

The renderer's legacy `proposition`, `premise`, and `inference` field names are
storage terms. Learner-facing labels and bridges use the current work mode's
vocabulary; they must not describe a historical cause, practical condition, or
literary clue as a deductive premise unless that is genuinely its role.

## Progressive disclosure

Default question view shows only:

- target;
- direct grounds;
- complete reasoning bridge.

Clicking a reviewable statement reveals its source excerpt, plain explanation,
relation role, and mastery criterion. Clicking “deeper grounds” opens the
next lower layer in place. Expansion never sends the learner to a new proof
page.

Primary reasoning content is never hidden behind a redundant opening action.
Entering a question page presents its local map directly after a compact
question header. Long source-location notes, broader summaries, and route
context remain available without delaying the current reasoning task.

Future questions show their wording, source position, and problem-chain
context, but no answer or proof. If learner state says a question was completed
while its local map has not yet been structured, say that explicitly rather
than inventing one.

## Progress

The separate progress page uses the same source hierarchy. It shows:

- reading position: completed governing questions / total questions;
- strict mastery: inferences at reconstructable or stronger / eligible
  inferences;
- current source unit and current question;
- expandable source units with their questions and statuses.

Never merge reading and mastery into one score. A learner may have reached a
chapter without being able to reconstruct its argument.

## Interaction and deep links

- `#contents` opens the source contents.
- `#unit=<stable-id>` opens one source-unit landing page.
- `#question=<stable-id>` opens one unique question page.
- Legacy proposition hashes resolve to their governing question where
  possible.
- Browser back/forward works through hash navigation.
- Page navigation may return the ordinary document scroll to the top.
- No interaction captures pointer movement or overrides wheel scrolling.
- The “current” action links directly to the active question.

## Visual hierarchy

Use a restrained academic editorial interface:

- serif headings and reading text;
- sans-serif navigation, status, and controls;
- warm paper-like neutral surfaces;
- teal for established/current structure and amber for active attention;
- opaque semantic proof surfaces, not glass effects;
- 4/8px spacing rhythm;
- compact display scale, not oversized decorative type.

Color never acts alone. Each proposition and inference surface uses an
indivisible tuple:

```text
background + primary text + secondary text + border
```

All primary and secondary text pairs pass 4.5:1 in light and dark modes.

## Responsive and accessible behavior

- desktop: persistent or collapsible sidebar and one readable main column;
- mobile: drawer navigation and one-column question page;
- no horizontal page overflow;
- at least 16px reading text;
- at least 44px interactive targets;
- browser zoom remains enabled;
- viewport meta, skip link, sequential headings, semantic `details/summary`;
- visible `:focus-visible`;
- meaningful labels and `aria-current`;
- reduced-motion support;
- full keyboard access.

## Standalone and live modes

The HTML embeds one complete JSON snapshot and works as a standalone file.
Actual browser acceptance uses a local HTTP preview so deep links, console
checks, desktop, and mobile layouts are tested in realistic conditions.

## Acceptance tests

Reject if any is false:

1. The source structure is the primary entry.
2. Each source unit exposes its role, children, and assigned questions.
3. Each question has one canonical deep-linked page.
4. Related source units do not duplicate question pages.
5. The whole-book problem chain remains available as a secondary index.
6. Previous and next problem pressure is visible on each question page.
7. The local map is directly available and precedes secondary route context.
8. Long source-location notes do not push the local map out of the initial
   reading flow.
9. The target is above and the grounds are below.
10. Direct grounds are visible; deeper grounds disclose downward.
11. Every relation bridge contains complete untruncated text.
12. Future answers remain hidden.
13. No canvas, SVG graph, pan, or zoom interaction remains.
14. Reading position and strict mastery remain separate.
15. Desktop, 375px mobile, light, dark, and reduced-motion views are operable.
16. Runtime, proof, contrast, deep validation, unit, interaction, and browser
    console checks pass.
