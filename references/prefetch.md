# Persistent multi-unit prefetch

Read this only for batch prefetch, resume, progress inspection, or handoff
diagnosis. Runtime state under `prefetch/` is optional sidecar data;
`course.json` remains the sole learning-progress authority.

## User contract

Accept these short requests without asking for ids, revisions, page ranges,
locators, output names, worker counts, or JSON parameters:

- `预制后续全部单元` — queue all remaining units;
- `预制下一批` — extend the queue by five not-yet-targeted units;
- `继续预制` — recover an interrupted coordinator and continue;
- `预制进度` — validate and report the batch receipt.

Resolve the course from an explicit book title or the sole active course. If
several remain genuinely ambiguous, ask only for the book title.

## Plan and resume

For all remaining units:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-plan <course-dir> --mode remaining
```

For the next default batch:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-plan <course-dir> --mode next-batch
```

On explicit resume after the previous coordinator has ended:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-resume <course-dir>
```

Resume preserves every staged attempt. Do not call it while another coordinator
is still active because it deliberately releases that coordinator's claims.

## Coordinator loop

Use available parallel capacity, normally no more than three active workers.
Prioritize source order so the learner's nearest missing unit finishes first.
Create a unique opaque token for every generator or reviewer context.

### Generate

Atomically claim one unit:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-claim <course-dir> \
  --role generator --worker-token <unique-generator-token>
```

Give the generator only the returned unit, authoritative source, safe context,
and [unit-preparation.md](unit-preparation.md). It must extract the exact complete
unit, validate its boundaries, build the full question tree, and cover every
substantive source span. Persist the normalized candidate before starting any
review:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  stage-prefetch-unit <course-dir> \
  --tree <tree.json> --source-text <unit.txt> \
  --expected-unit <claimed-unit-id> \
  --worker-token <same-generator-token>
```

Staging creates an immutable attempt directory. A later session can resume from
it without regenerating content.

### Independently review

Use a fresh context that did not generate the unit:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-claim <course-dir> \
  --role reviewer --worker-token <unique-reviewer-token>
```

The runtime refuses to give a unit back to its generator as reviewer. Give the
reviewer only:

- staged exact unit text;
- staged normalized tree;
- node, coverage, and review contracts;
- the instruction to falsify source completeness, coverage, support, scope,
  structure, and citation exactness.

Never give it generator reasoning, intended verdict, suspected issues, or prior
repair explanations.

For a failed verdict, persist the exact report:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  record-prefetch-review <course-dir> \
  --review <failed-review.json> \
  --expected-unit <claimed-unit-id> \
  --worker-token <same-reviewer-token>
```

The job becomes `repairing`. Claim it with a generator token, repair every
issue, stage a new attempt, and use another fresh reviewer context. Repeat until
the exact candidate passes.

For a passed verdict, install only the staged hashes reviewed by that worker:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  cache-unit <course-dir> \
  --tree <staged-tree.json> --review <passed-review.json> \
  --source-text <staged-unit.txt> --expected-unit <claimed-unit-id> \
  --worker-token <same-reviewer-token>
```

The runtime checks worker separation, source and course fingerprints, source
unit metadata, staged hashes, normalized tree, all six review checks, empty
passed issues, and review hashes. It removes any old ready marker first and
writes `package.json` last.

## Terminal receipt

After each wave, and always before ending, run:

```bash
python3 /absolute/path/to/book-grilling/scripts/book_grilling.py \
  prefetch-status <course-dir>
```

The only successful batch terminal is:

```json
{
  "status": "ready",
  "complete": true,
  "counts": {
    "ready": 12
  }
}
```

`consumed` units may appear after learning has already activated them and also
count as complete. Any other status means the batch is partial. Never say
“预制完成” while work is queued, generating, pending review, reviewing,
repairing, blocked, or stale. If the session must end, state the exact counts
and tell the learner that `继续预制` resumes without discarding work.

## Storage and ordered consumption

```text
<course-dir>/.book-grilling/prefetch/
  batch.json
  jobs/<unit-id>/job.json
  jobs/<unit-id>/attempts/<n>/unit.txt
  jobs/<unit-id>/attempts/<n>/tree.json
  jobs/<unit-id>/attempts/<n>/review.json
  units/<unit-id>/unit.txt
  units/<unit-id>/tree.json
  units/<unit-id>/review.json
  units/<unit-id>/package.json
```

Learning consumes only the exact next unit. Later ready units remain isolated;
a hole never permits skipping. Promoted packages move to
`.book-grilling/history/prefetch/`. Invalidating a unit marks affected queued or
ready work stale and preserves its evidence for audited repair.
