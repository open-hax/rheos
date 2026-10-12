#!/usr/bin/env python3
"""Offline GREEN evidence packaging; no product, board, Git index or runtime writes.

Default mode verifies the frozen publication against local originals. --build
creates this directory's generated artifacts once and refuses existing outputs.
Git use is read-only for baseline objects and diff measurement. No source imports.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tarfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DIAG = ROOT / '.ημ/diagnostics'
RUNNER = DIAG / 'design-frontmatter-green-runner-01'
RUN = RUNNER / 'runs/green-01'
RED = '171c4f22ebb25db4af40ee3e51f6d4a32e373467'
BASE = 'ef3c4ab'
DIRECT_RAW = {
    '.ημ/diagnostics/design-frontmatter-green-root-closure01.json',
    '.ημ/diagnostics/design-frontmatter-green/SOURCE-PROOF.json',
    '.ημ/diagnostics/design-frontmatter-green/independent-source-review.json',
}
CACHE = '.ημ/diagnostics/design-frontmatter-green-runner-01/warm-prior.tar.gz'
COMPANIONS = [
    '.ημ/receipts.edn', '.ημ/session-mycology/ledger.md',
    '.ημ/diagnostics/design-frontmatter-green-canonical-closure.json',
]
SOURCE_CHANGES = [
    'docs/cli.md', 'src/rheos/backend/infra/agent_tools.cljs',
    'src/rheos/backend/infra/cli.cljs', 'src/rheos/backend/law/frontmatter.cljs',
    'src/rheos/backend/law/frontmatter.cljc',
    'test/rheos/backend/infra/http_server_test.cljs',
]
OUTPUTS = ['package.py', 'AUXILIARY.jsonl', 'AUXILIARY-MAP.json',
           'ROUNDTRIP.json', 'CACHE-REFERENCE.json', 'RESULT.md',
           'PACKAGING.md', 'STAGING.txt', 'SHA256SUMS']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rel(path):
    return path.relative_to(ROOT).as_posix()


def git(*args):
    return subprocess.check_output(['git', '-c', 'core.quotePath=false', *args], cwd=ROOT)


def load(path):
    return json.loads(path.read_bytes())


def entry(path):
    data = path.read_bytes()
    return {'path': rel(path), 'bytes': len(data), 'sha256': sha(data)}


def raw_inventory():
    paths = [p for directory in [RUNNER, DIAG / 'design-frontmatter-green']
             for p in directory.rglob('*') if p.is_file()]
    paths += [DIAG / f'design-frontmatter-green-root-{name}01.json'
              for name in ['closure', 'preparation', 'release']]
    return sorted(paths, key=rel)


def verify_inputs():
    closure = load(DIAG / 'design-frontmatter-green-root-closure01.json')
    assert sha((DIAG / 'design-frontmatter-green-root-closure01.json').read_bytes()) == 'faf2a602c52d2d9f9c71e7fcfb3724ca694ba8a7c0953a3180feee91cefd7c8a'
    for name, expected in closure['execution_files'].items():
        row = entry(RUN / name)
        assert all(row[k] == expected[k] for k in ['bytes', 'sha256']), name
    assert len(closure['execution_files']) == 50
    assert {rel(p) for p in RUN.rglob('*') if p.is_file()} == {rel(RUN / n) for n in closure['execution_files']}
    source = load(RUNNER / 'source-pins.json')
    exceptions = []
    for name, digest in source['files'].items():
        p = pathlib.Path(name)
        data = p.read_bytes()
        if sha(data) != digest:
            name_rel = rel(p)
            assert name_rel in COMPANIONS[:2], name
            prior = git('show', f'{RED}:{name_rel}')
            assert sha(prior) == digest and data.startswith(prior), name
            exceptions.append({'path': name_rel, 'pinned_RED_bytes': len(prior),
                               'pinned_RED_sha256': digest, 'prefix_preserved': True,
                               'reason': 'Root-authorized post-run append; excluded from immutable raw package.'})
    prep = load(RUNNER / 'preparation-hashes.json')
    for name, digest in prep.items():
        assert sha((RUNNER / name).read_bytes()) == digest, name
    manifest = (RUNNER / 'SHA256SUMS').read_bytes()
    assert sha(manifest) == closure['manifest_sha256']
    manifest_rows = []
    for line in manifest.decode().splitlines():
        digest, name = line.split('  ', 1)
        path = RUNNER / name
        assert sha(path.read_bytes()) == digest, name
        manifest_rows.append(name)
    warm = load(RUNNER / 'warm-before.json')
    cache_data = (ROOT / CACHE).read_bytes()
    assert len(cache_data) == 7430065
    assert sha(cache_data) == '0666ef9b0d37a97c8e58f909e422f3bee0710752942a6bb9f6e6235888c8f1dc'
    warm_seen = set()
    total = 0
    with tarfile.open(ROOT / CACHE) as archive:
        members = archive.getmembers()
        for member in members:
            assert member.isfile() and member.name not in warm_seen
            warm_seen.add(member.name)
            data = archive.extractfile(member).read()
            assert sha(data) == warm['files'][str(ROOT / member.name)], member.name
            total += len(data)
    assert len(members) == warm['count'] == 480
    assert total == warm['bytes'] == 50315678
    assert {str(ROOT / p) for p in warm_seen} == set(warm['files'])
    execution = load(RUN / 'execution.json')
    assert execution['execution_closed'] and execution['error'] is None
    for key in ['source_changed', 'source_file_sets_changed', 'preparation_changed', 'verification_errors']:
        assert not execution[key], key
    assert len(closure['stages']) == 7 and all(s['exit'] == 0 and s['closed'] for s in closure['stages'])
    for name in ['compile', 'explicit-node-test']:
        text = (RUN / name / 'stdout.log').read_text()
        assert re.findall(r'^Ran (\d+) tests containing (\d+) assertions\.$', text, re.M) == [('166', '1361')]
        assert re.findall(r'^(\d+) failures, (\d+) errors\.$', text, re.M) == [('0', '0')]
    text = (RUN / 'build/stdout.log').read_text()
    assert all(re.search(r'^\[:' + target + r'\] Build completed\. .*0 warnings,', text, re.M)
               for target in ['server', 'cli', 'github-sync', 'app'])
    old_names = git('diff', '--no-renames', '--name-only', '-z', BASE, RED).decode().split('\0')[:-1]
    assert len(old_names) == 73
    prior_diagnostics = [name for name in old_names if name.startswith('.ημ/diagnostics/')]
    for name in prior_diagnostics:
        assert (ROOT / name).read_bytes() == git('show', f'{RED}:{name}'), name
    return {'closure': closure, 'raw_execution_verified': 50,
            'source_pins': len(source['files']), 'source_matching_now': len(source['files']) - len(exceptions),
            'root_provenance_append_exceptions': exceptions, 'preparation_verified': len(prep),
            'manifest_rows_verified': len(manifest_rows), 'cache_members_verified': len(members),
            'cache_expanded_bytes': total, 'RED_changed_paths': old_names,
            'unchanged_committed_diagnostic_paths': len(prior_diagnostics)}


def write(name, data):
    path = HERE / name
    with path.open('xb') as out:
        out.write(data)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def build():
    for name in OUTPUTS:
        if name != 'package.py':
            assert not (HERE / name).exists(), f'Will not overwrite {name}'
    check = verify_inputs()
    originals = raw_inventory()
    packed = [p for p in originals if rel(p) not in DIRECT_RAW | {CACHE}]
    records = []
    archive = b''
    for number, path in enumerate(packed, 1):
        data = path.read_bytes()
        text = data.decode('utf-8')
        assert text.encode('utf-8') == data
        record = {**entry(path), 'text': text}
        archive += (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        records.append({**entry(path), 'record': number, 'representation': 'AUXILIARY.jsonl'})
    write('AUXILIARY.jsonl', archive)
    direct = [entry(ROOT / name) for name in sorted(DIRECT_RAW)]
    cache = entry(ROOT / CACHE)
    prospective = sorted(set(SOURCE_CHANGES + COMPANIONS + list(DIRECT_RAW) + [rel(HERE / name) for name in OUTPUTS]))
    cumulative = sorted(set(check['RED_changed_paths']) | set(prospective))
    red_history = []
    for name in check['RED_changed_paths']:
        data = git('show', f'{RED}:{name}')
        red_history.append({'path': name, 'bytes': len(data), 'sha256': sha(data)})
    mapping = {'schema': 'rheos-green-publication/v1', 'RED_commit': RED,
               'base': git('rev-parse', BASE).decode().strip(),
               'scope': 'Every newly fixed diagnostic original in the two GREEN directories and three root preparation/release/closure records. Live canonical/provenance companions excluded and published directly.',
               'archive': {**entry(HERE / 'AUXILIARY.jsonl'), 'encoding': 'UTF-8 JSONL; exact original UTF-8 text, no normalization'},
               'packed': records, 'direct': direct,
               'binary_reference_only': [{**cache, 'reason': 'Generated warm cache backup, not product source; retained locally with complete 480-file manifest in archive.'}],
               'excluded_live_direct_companions': COMPANIONS,
               'RED_history_at_commit': red_history,
               'RED_path_command': ['git', '-c', 'core.quotePath=false', 'diff', '--no-renames', '--name-only', '-z', BASE, RED],
               'prospective_staging_paths': prospective,
               'cumulative_changed_paths_no_renames': cumulative,
               'path_count_limit': 'Union of exact RED diff paths and explicit current publication paths; final staged/native hosted diff remains root-owned.',
               'original_count': len(originals), 'original_bytes': sum(p.stat().st_size for p in originals),
               'packed_count': len(packed), 'packed_original_bytes': sum(p.stat().st_size for p in packed),
               'packed_empty_files': sum(p.stat().st_size == 0 for p in packed),
               'no_raw_original_deleted_or_modified': True}
    write('AUXILIARY-MAP.json', json_bytes(mapping))
    write('CACHE-REFERENCE.json', json_bytes({
        'archive': cache, 'publish_binary': False, 'retained_locally': True,
        'manifest': entry(RUNNER / 'warm-before.json'),
        'manifest_archive_record': next(row['record'] for row in records if row['path'].endswith('/warm-before.json')),
        'read_only_tar_verification': {'members': check['cache_members_verified'], 'expanded_bytes': check['cache_expanded_bytes'], 'all_member_hashes_match_manifest': True, 'no_extraction': True},
        'limit': 'Reference proves identity and local archival verification. The generated binary itself is deliberately not in the product review; this is not a fresh hosted cache reconstruction claim.'}))
    decoded = [json.loads(line) for line in archive.splitlines()]
    assert len(decoded) == len(packed) and len({row['path'] for row in decoded}) == len(decoded)
    for row, path in zip(decoded, packed):
        data = row['text'].encode()
        assert row['path'] == rel(path) and data == path.read_bytes()
        assert len(data) == row['bytes'] and sha(data) == row['sha256']
    proof = {k: v for k, v in check.items() if k not in ['closure', 'RED_changed_paths']}
    proof.update({'packed_records': len(decoded), 'packed_original_bytes': mapping['packed_original_bytes'],
                  'encoded_bytes': len(archive), 'empty_files': mapping['packed_empty_files'],
                  'all_path_byte_count_hash_and_exact_text_roundtrips': True,
                  'all_original_paths_unique_and_exhaustively_classified': True,
                  'archive_sha256': sha(archive),
                  'process_limit': '18 PID absences are audited from root closure; packaging performs no live process probe.',
                  'offline_check_history': 'An initial strict all-224-current-hash assertion exposed the two expected root-authorized post-run ledger appends. Follow-up verified each pinned RED prefix exactly; no product/source pin changed. This is packaging validation history, not a test/build failure.'})
    write('ROUNDTRIP.json', json_bytes(proof))
    write('STAGING.txt', ('\n'.join(prospective) + '\n').encode())
    stages = '\n'.join(f"| {s['name']} | {s['exit']} | {s['elapsed_s']:.6f} |" for s in check['closure']['stages'])
    result = f'''# Design metadata GREEN: local qualification and publication boundary

The existing mutable-frontmatter policy now accepts `design`; the pure law moved from `.cljs` to `.cljc`. The CLI/tool discovery lists and CLI documentation expose the same existing operation. Existing canonical writer, refusals, serializer, event append and route behavior remain the implementation boundaries. Source and tests are published as ordinary files, including the one `^js` test-fixture hint repair recorded separately. This package changes no implementation.

The RED checkpoint is `{RED}` (166 tests, 73 failures, zero errors). The new local GREEN run completed seven gates in **102.476825 seconds**, from 2026-10-07T19:32:58.433349Z through 19:34:40.910170Z. Both compile autorun and the explicit Node test invocation report **166 tests, 1,361 assertions, zero failures and zero errors**. Root closure records all stages closed and all 18 observed owned PIDs absent. Packaging independently verifies all 50 execution-file hashes; it does not repeat runtime or process probes.

| Stage | Exit | Elapsed seconds |
| --- | ---: | ---: |
{stages}

Lint reports zero errors and zero warnings, with informational diagnostics retained. LSP diagnostics passed its configured gate. The test compiler and all four release targets (`server`, `cli`, `github-sync`, `app`) report zero compiler warnings. This does **not** mean all output was warning-free: raw stderr preserves the PNPM `.npmrc` unresolved `${{NPM_TOKEN}}` advisory, clj-kondo config-copy/progress messages, the optional `source-map-support` notice, and expected CLI refusal messages from negative tests. No secret value is exposed by the unresolved variable name. Full stdout/stderr, empty files, carriage returns and escape sequences are retained byte-for-byte in the archive.

The earlier SOURCE-PROOF and preparation records intentionally still describe their earlier, unexecuted stage. The root closure and this successor summary record the later completed GREEN result; historical claims were not rewritten. Of 224 pinned inputs, 222 still match exactly at packaging. The two exceptions are root-authorized receipt/mycology appends after execution; their original pinned RED prefixes remain byte-identical. All 53 preparation hashes and all prior committed diagnostic files remain unchanged.

This is local qualification, not a hosted review, operational deployment, board transition or downstream Truth activation. The existing workflow caller remains unchanged. Its pinned reusable workflow and setup behavior are not qualified merely by these local gates. The local warm-cache backup is retained and checked against its 480-file manifest, but is not product source and is not added as a generated binary to review.

The complete mapping is [AUXILIARY-MAP.json](AUXILIARY-MAP.json), the exact text archive is [AUXILIARY.jsonl](AUXILIARY.jsonl), and the verification result is [ROUNDTRIP.json](ROUNDTRIP.json). The direct root closure is [design-frontmatter-green-root-closure01.json](../design-frontmatter-green-root-closure01.json). Root owns final staging, hosted policy checks and publication.
'''
    write('RESULT.md', result.encode())
    plan = f'''# Lossless GREEN publication plan

The committed RED history remains intact: **73 changed paths** against `{BASE}`. This package classifies **{len(originals)} new fixed diagnostic originals**: **{len(packed)} UTF-8 textual originals packed**, **{len(direct)} textual originals kept direct**, and **one generated warm-cache archive referenced only**. Packed originals total **{mapping['packed_original_bytes']:,} bytes**; exact compact JSONL is **{len(archive):,} bytes**, including **{mapping['packed_empty_files']} empty originals**. No raw local original is deleted or rewritten.

Each archive record contains the repository-relative original path, byte count, SHA-256 and exact UTF-8 text. JSON escaping carries embedded newlines, CR/ANSI output and arbitrary valid UTF-8 losslessly. Every decoded record is compared with the original bytes, not only its hash. The map classifies every selected original once. Package files themselves are new derived artifacts, separate from the original inventory.

`STAGING.txt` lists **{len(prospective)} prospective staging paths**, including the deleted `.cljs` path and replacement `.cljc`, existing direct source/test changes, the two root-owned append-only ledgers, the root canonical closure companion, three direct raw records and nine package files. It does not stage anything. The union with the 73 RED paths is **{len(cumulative)} cumulative changed path names with renames disabled**. Rename-aware hosting may count the law move as one file; no universal host file allowance or review completion is inferred from this count. All prior test changes remain ordinary direct files in the cumulative diff.

The 7,430,065-byte `warm-prior.tar.gz` stays local. Its immutable SHA-256 is `0666ef9b0d37a97c8e58f909e422f3bee0710752942a6bb9f6e6235888c8f1dc`. The full manifest is archive record **{next(row['record'] for row in records if row['path'].endswith('/warm-before.json'))}**, SHA-256 `a99070af9175868956c11e75a1b1356f72767ec131d093f12e45e3b89babf6f5`. Read-only tar inspection verified all **480 regular members / 50,315,678 expanded bytes** against that manifest, without extraction or execution. This deliberate generated-cache exclusion is explicit; it is not an omitted textual diagnostic.

Source review and original-source proof stay direct for review convenience. Root's post-run ledgers and canonical closure companion remain outside the immutable raw inventory, because root owns their final append/publication. The current `.github/workflows/eta-mu-evidence-review.yml` has no explicit `review_timeout_minutes` input; its pinned upstream workflow supplies the default. This packaging does not alter or claim a larger timeout.

Offline verification: `python3 .ημ/diagnostics/design-frontmatter-green-publication/package.py` verifies the frozen map/archive, all selected originals, source/preparation pins with the two explicit append-only exceptions, old diagnostic history and warm-cache members. It performs only file reads and read-only Git object/diff commands; no source import, JVM, native operation, service, build or test. Generated files were created once with the same script's `--build` mode; existing outputs are never overwritten by that mode.

Final staged patch bytes remain a root publication check: this plan reports an exact path inventory and original/archive bytes, not an invented hosted serialized-diff size. Root can measure the final explicit staged set with `git -c core.quotePath=false diff --cached --binary --no-renames {BASE}` once root has completed its companions and staged the listed paths. This agent has not modified the index or committed anything.
'''
    write('PACKAGING.md', plan.encode())
    manifest_paths = [HERE / name for name in OUTPUTS if name != 'SHA256SUMS']
    manifest_paths += [ROOT / name for name in sorted(DIRECT_RAW)]
    manifest_paths += [ROOT / name for name in SOURCE_CHANGES if (ROOT / name).is_file()]
    lines = [f'{sha(p.read_bytes())}  {rel(p)}' for p in sorted(manifest_paths, key=rel)]
    write('SHA256SUMS', ('\n'.join(lines) + '\n').encode())
    verify()


def verify():
    check = verify_inputs()
    mapping = load(HERE / 'AUXILIARY-MAP.json')
    archive = (HERE / 'AUXILIARY.jsonl').read_bytes()
    assert sha(archive) == mapping['archive']['sha256']
    rows = [json.loads(line) for line in archive.splitlines()]
    assert len(rows) == mapping['packed_count']
    assert len({row['path'] for row in rows}) == len(rows)
    for i, (row, expected) in enumerate(zip(rows, mapping['packed']), 1):
        assert row['path'] == expected['path'] and expected['record'] == i
        data = row['text'].encode('utf-8')
        assert data == (ROOT / row['path']).read_bytes()
        assert len(data) == row['bytes'] == expected['bytes']
        assert sha(data) == row['sha256'] == expected['sha256']
    for row in mapping['direct'] + mapping['binary_reference_only']:
        assert entry(ROOT / row['path']) == {k: row[k] for k in ['path', 'bytes', 'sha256']}
    classified = [row['path'] for group in ['packed', 'direct', 'binary_reference_only'] for row in mapping[group]]
    assert len(classified) == len(set(classified))
    assert set(classified) == {rel(p) for p in raw_inventory()}
    for line in (HERE / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert sha((ROOT / name).read_bytes()) == digest, name
    print(json.dumps({'verified': True, 'originals': len(classified), 'packed': len(rows),
                      'packed_original_bytes': sum(row['bytes'] for row in rows),
                      'encoded_bytes': len(archive), 'source_matching_now': check['source_matching_now'],
                      'root_append_exceptions': len(check['root_provenance_append_exceptions']),
                      'manifest_sha256': sha((HERE / 'SHA256SUMS').read_bytes())}, ensure_ascii=False))


if __name__ == '__main__':
    assert sys.argv[1:] in [[], ['--build']], 'Only optional --build is accepted'
    build() if sys.argv[1:] == ['--build'] else verify()
