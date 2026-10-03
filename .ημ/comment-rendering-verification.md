# Comment separator rendering repair

Issue: <https://github.com/open-hax/rheos/issues/1>.
Base: `11811264a308d406cb612aefa1dad40818675e5e`.
Red commit: `2ec344f`.

`shape/content-parser` now inserts blank lines on both sides of comment content
inside its existing `---` delimiters. The parser still recognizes the same
body/comment section boundaries. Text inside the sections is unchanged. The
existing append path (`infra/task-edit/append-comment!` →
`domain/task-edit/plan-comment` → `append-comment` → `inject-write-id`) uses
that same serialization boundary; no board writer or event format was added.

## Red and green

- Real multi-paragraph engine-authored comments from Foresight #125 and SHX #1
  are captured in `test/rheos/backend/shape/comment_fixtures.cljs`, with their
  review-comment provenance. `marked` is already a declared development
  dependency. Its lexer detects unintended headings, rather than merely
  checking an implementation string.
- Before the fix, the full test artifact ran **153 tests / 790 assertions**:
  **4 rendering failures, 0 errors**, direct `node dist/test.cjs` exit **1**.
  Round-trip, original section content, and historical ledger prefix assertions
  passed. `shadow-cljs compile test` itself exits 0 after its autorun failures;
  the separately executed artifact supplies the truthful failing exit.
- After the fix, `pnpm test` exits **0**, **153 tests / 790 assertions**, **0
  failures / 0 errors**. Test compilation: **139 files, 0 warnings**. The same
  artifact also passes under **Node 22.20.0** with the same counts.
- `clj-kondo --lint src test`: exit **0**, **0 errors / 0 warnings**. Eight
  existing layer-boundary information messages remain visible.
- `pnpm exec shadow-cljs release cli`: exit **0**, **106 files, 0 warnings**.
- `git diff --check`: exit **0**.

The standalone source dependencies were bootstrapped with the repository's
existing `scripts/bootstrap-source-deps.sh`; its declared donor/chat-ui pins
were unchanged. The repository has no committed package lock. Local dependency
installation used `pnpm install --ignore-scripts --lockfile=false`, pnpm
10.15.0. Build/test orchestration used Node 24.14.1, shadow-cljs 3.5.4, marked
18.0.14. Node 22.20.0 was separately used for the complete test artifact and
the compiled CLI smoke. No package policy or dependency declaration changed.

## Compiled CLI consumer-copy proof

Artifact, retained only in the isolated checkout:

```text
/home/err/spaces/review-repair/rheos-comment-rendering/dist/cli.cjs
sha256: 83c6b397278d418d69ce6509b8c3d9fe87e88cca9141b28143d9efb5d78a75a7
```

The artifact's `read-task` and `comment` verbs were run against isolated copies
of the actual Foresight #125 card and three affected SHX #1 cards. Every legacy
final paragraph first reproduced a setext heading. After one normal comment
operation per copy:

- all pre-existing section content/types and descriptive frontmatter matched;
- the engine generated a different write ID and exactly one new event;
- the complete previous event ledger byte prefix matched;
- neither the old final paragraph nor the new comment rendered as a heading;
- the original consumer cards and source ledgers remained byte-identical.

Copied Foresight ledger: **131359 bytes**, SHA-256
`5e8254a15747198059604e228954a870d0442e901c9d469bb318ac0b8caf7bce`.
Initial copied SHX ledger: **43059 bytes**, SHA-256
`c02cec744ef60c77c682e7a4ccf15a0d8c5e0c767ddaf6960bc91a5adb1e5093`.

Local ignored verification directory:
`.ημ/formatter-verification/` contains the red/green/build/kondo logs,
`cli-smoke.mjs`, and `cli-smoke.json`. The smoke script calls Rheos for board
reads/writes; it does not parse or construct board event records.

## Canonical consumption by the coordinator

After qualifying the repair, invoke the built artifact directly. No global
runtime replacement, PM2 change, or deployment is necessary. The CLI expects
the verb first. Record a truthful formatter-repair update through `comment`;
that operation normalizes existing separators and appends its normal event.
Do not issue an empty frontmatter update, invent a write ID/event, or manually
rewrite comment sections or historical ledger bytes.

Example invocation for the owning coordinator (not executed on the consumers):

```bash
/home/err/.volta/tools/image/node/22.20.0/bin/node \
  /home/err/spaces/review-repair/rheos-comment-rendering/dist/cli.cjs \
  comment 146f1b47-c6a7-5a37-996b-a381dd91f6b6 \
  --config /home/err/spaces/review-repair/fork-plan/openhax.kanban.edn \
  --text 'Applied the qualified upstream Rheos comment formatter: existing prose and section content are preserved; historical event bytes remain unchanged.'
```

Use the same `comment` operation with the SHX checkout's
`openhax.kanban.edn` and these existing identities:
`shx-kanban-hexis-assembler`, `shx-kanban-migrate-ledgers-to-clio`, and
`shx-kanban-process-inbox`. Review and commit the resulting engine-authored
card/ledger diffs in their owning PRs. The formatter PR itself changes no
consumer file or historical event ledger. The coordinator owns review
requests, external settlement, and merge.
