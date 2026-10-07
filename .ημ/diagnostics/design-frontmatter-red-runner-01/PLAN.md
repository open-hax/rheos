# Rheos design frontmatter RED: unexecuted runner preparation

This is preparation for one root-released attempt in the isolated Rheos checkout
at `ef3c4abf1ea75199486f693e9470df3fec88dd49`. It does not execute, qualify, or
change the frozen four RED files. The existing 13 new tests require actual
compilation and execution before any failure can be accepted as meaningful RED.
Root owns the resource release after its native lane closes.

The [existing package script](../../../package.json) invokes `shadow-cljs compile
test && node dist/test.cjs`. The [existing target](../../../shadow-cljs.edn) is
`:node-test`, includes the `-test$` namespaces, writes `dist/test.cjs`, and has
`:autorun true`. Those settings remain unchanged. This runner uses the installed
local CLI and `--force-spawn` to prevent attaching to an existing Shadow server.
It records any compile-stage autorun separately; the second stage explicitly
executes the generated bundle under Node 22 and records its own exit code.

## Exact proposed launch — requires root release

From `/home/err/spaces/foresight/.worktrees/rheos-design-frontmatter`:

```bash
python3 .ημ/diagnostics/design-frontmatter-red-runner-01/supervisor.py red-01
```

The fresh `runs/red-01` directory is created exclusively. No overwrite or retry is
implemented. The child commands, in order, are:

```text
/home/err/.volta/tools/image/node/22.20.0/bin/node /home/err/spaces/foresight/.worktrees/rheos-design-frontmatter/node_modules/shadow-cljs/cli/runner.js --force-spawn compile test
/home/err/.volta/tools/image/node/22.20.0/bin/node /home/err/spaces/foresight/.worktrees/rheos-design-frontmatter/dist/test.cjs
```

The Node test stage is admitted only after compile exit 0, its owned group is
closed, a nonempty fresh bundle exists, and the compile-completion marker is
present. A pre-existing bundle or checkout `.shadow-cljs` directory refuses this
first attempt; a failed attempt requires a separately reviewed next action.

The child environment removes inherited `JAVA_OPTS`, `JAVA_TOOL_OPTIONS`,
`JDK_JAVA_OPTIONS`, `_JAVA_OPTIONS`, `CLJ_JVM_OPTS`, `JVM_OPTS`, `NODE_OPTIONS`,
`NODE_PATH`, `XDG_CONFIG_HOME`, and `LOCALAPPDATA`, without recording their values.
It then sets only `JAVA_TOOL_OPTIONS=-Xms256m -Xmx2g -XX:ActiveProcessorCount=2`
for JVM sizing, prefixes the explicit Node 22 and Java 21 binary directories to
PATH, and sets `CI=true` and `npm_config_ignore_scripts=true`. The pinned project
config has no JVM override; the home Shadow config must be absent. These JVM
options therefore cover both Shadow's dependency resolver JVM and its compiler
JVM. No lifecycle script, server/watch target, classpath-only probe, or global
configuration change is requested.

## Finite budget and evidence basis

One monotonic clock starts before wrapper argument/preflight work. Both stages,
including the target's inherited autorun, share **280 seconds of work**. Cleanup
has only the remaining time up to **300 seconds total**; it is not another
300-second allowance. A pre-spawn check follows source hashing, and a post-wait
check rejects a late child result even if polling missed the boundary. The final
verdict also rejects exceeding total time. No second stage begins after failure.

The [dependency setup](../design-frontmatter-setup-01/CLOSURE.json) already
installed Node dependencies and verified the 31 source-dependency files. This
checkout has no compiler cache, and the installed Shadow 3.5.5's matching Maven
artifact is absent; Helix 0.2.2 and Malli 0.16.4 JARs are present. The cache facts
and hashes are in [PROVENANCE.json](PROVENANCE.json). They justify using the full
authorized ceiling, not a prediction that a cold dependency resolution/compile
will finish within it. A timeout is failed execution, never meaningful RED, and
never permits an automatic retry or silently shortened test selection.

Cleanup signals only an owned newly created process group, with PID/start-time
reuse checks, then reaps the direct child and checks the group plus every
observed identity. Optional unrelated `/proc/<pid>/exe` or `cwd` permission denial
does not determine group membership; unreadable stat membership remains an
explicit failure, not proof of absence. The primary PID, boot, start ticks and
PGID are durably recorded immediately after spawn, followed by observed identity
changes. TERM has at most 12 seconds, clipped to leave five seconds within the
total lease; remaining owned processes receive KILL. Filesystem/OS stalls cannot
be forcibly bounded by Python polling. Any late/unreaped/unknown outcome stays a
failure; this preparation does not claim a tested hard real-time guarantee.

## Outcome interpretation and preserved output

Each stage has exact argv/cwd/times, full binary stdout/stderr, an append-only
ownership journal, primary identity and execution/cleanup record. The final
record preserves original failure and any final verification error separately.
The generated bundle is hashed before and after explicit Node execution. The
wrapper checks source byte hashes and complete `src`, `test`, and both copied
source-dependency file sets before each stage and at closure.

- Compile failure, missing/stale bundle, timeout, missing summary, test errors,
  uncertain process closure or source drift cannot be called meaningful RED.
- Explicit Node assertion failures with a nonzero exit are labelled
  `assertion-failures-root-review-required`. Root must inspect the actual failure
  locations and distinguish the intended design-key failures from other errors.
- A completed all-pass run is `unexpected-green-root-review-required`.
- Failure output with a zero exit is recorded as an exit-propagation problem.
- `execution_closed` describes successful collection/closure, not test success or
  implementation admission. The wrapper returns the explicit Node exit when
  collection closes; otherwise it returns 1.

The [source pins](source-pins.json) preserve all 94 earlier protected paths and
all 37 setup files, exact source-dependency bytes, direct npm package metadata,
installed resolution lock and selected compiler/runtime artifacts. This is not a
claim to freeze every transitive npm implementation byte or the entire JDK.
Process polling can miss brief descendants; final group absence and direct-child
reaping are recorded separately from the identities actually observed.

## Preparation status

Only filesystem reads, Python AST parsing and hash/file-set verification were
performed. No supervisor import, JVM, Node, build, classpath or test execution
occurred in this preparation. [STATIC-CHECKS.json](STATIC-CHECKS.json) records the
checks. Prior RED, setup, source, receipt and board files remain unchanged.
