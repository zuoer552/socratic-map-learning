# Cross-session next-unit prefetch

Read this only in a background session asked to prepare the next Book Grilling
unit, or when diagnosing its handoff.

## Short user contract

The learner should only need to say:

> 使用 book-grilling 预制下一单元，完成后停下。

Find the course from the workspace and book title. If exactly one learning
course exists, use it. If several are plausible and the conversation names no
book, ask only which book. Never ask for a unit id, revision, page range,
locator, output filename, or JSON parameter.

## Discover, prepare, cache

1. Run `prefetch-context <course-dir>`.
2. Obey its `prefetch.need`:
   - `prepare_prefetch_unit`: prepare the returned unit;
   - `wait_for_progress`: a valid cache already exists, or no later target is
     eligible; report the status and stop;
   - `activate_prefetched_unit`: the cached unit is already current and belongs
     to the learning session; do not mutate progress from the background
     session.
3. Use the returned source path and unit locator to extract the exact complete
   unit text. Do not infer a different unit or scan further ahead.
4. Build the unit tree and coverage ledger under
   [unit-preparation.md](unit-preparation.md).
5. Obtain a fresh independent passed review over the exact text and normalized
   tree.
6. Rerun `prefetch-context` before writing. If the target changed, discard the
   stale candidate or rebuild for the newly returned target.
7. Run:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  cache-unit <course-dir> \
  --tree <tree.json> \
  --review <review.json> \
  --source-text <unit.txt> \
  --expected-unit <unit-id-returned-by-prefetch-context>
```

`cache-unit` performs the final target, source, course, tree, review, and hash
checks. A stale or invalid candidate fails without changing learning progress.

## Storage and handoff

The optional cache is stored under:

```text
<course-dir>/.book-grilling/prefetch/units/<unit-id>/
  unit.txt
  tree.json
  review.json
  package.json
```

`package.json` is written last and is the ready marker. `course.json` remains
the sole authority for learning progress. Cache creation does not edit it or
the reader.

When the learner resolves the current unit's final node, `commit` validates and
promotes a ready cache atomically. A corrupt, stale, incomplete, or missing
cache is ignored and ordinary foreground preparation remains available. If the
background session finishes just after the boundary, the learning session's
next `context` returns `activate_prefetched_unit`.

After promotion, the consumed cache is moved out of the pending area and into
`.book-grilling/history/prefetch/`; it is no longer considered a look-ahead
candidate.

Invalidating a unit archives affected caches under
`.book-grilling/history/prefetch/`. Never repair live state by copying cache
files manually.
