"""Root-released Rheos RED only: shared 280s work, 300s total, no retry."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROC = Path('/proc')
WORK_SECONDS = 280.0
TOTAL_SECONDS = 300.0
NODE = Path('/home/err/.volta/tools/image/node/22.20.0/bin/node')
JAVA = Path('/usr/lib/jvm/java-21-openjdk-amd64/bin/java')
JVM_OPTIONS = '-Xms256m -Xmx2g -XX:ActiveProcessorCount=2'
LABEL = re.compile(r'[a-z0-9][a-z0-9-]{0,40}\Z')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def error_info(error):
    return {'type': type(error).__name__, 'message': str(error)}


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def membership(pid):
    """Stat is membership authority; optional exe/cwd metadata is separate."""
    try:
        fields = (PROC / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
        return {'pid': pid, 'state': fields[0], 'pgid': int(fields[2]),
                'starttime_ticks': int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def identity(pid):
    item = membership(pid)
    if item is None:
        return None
    item['metadata_errors'] = {}
    for field in ['exe', 'cwd']:
        try:
            item[field] = os.readlink(PROC / str(pid) / field)
        except OSError as error:
            item[field] = None
            item['metadata_errors'][field] = error_info(error)
    return item


def group_members(pgid):
    result = {'members': [], 'unreadable': []}
    try:
        paths = list(PROC.iterdir())
    except OSError as error:
        result['unreadable'].append(error_info(error))
        return result
    for path in paths:
        if not path.name.isdecimal():
            continue
        try:
            item = membership(int(path.name))
            if item and item['pgid'] == pgid:
                result['members'].append(item)
        except (OSError, ValueError, IndexError) as error:
            result['unreadable'].append({'pid': int(path.name), **error_info(error)})
    return result


def changed(pins):
    return [p for p, h in pins.items() if not Path(p).is_file() or digest(Path(p)) != h]


def changed_trees(trees):
    return [root for root, expected in trees.items()
            if sorted(str(p.relative_to(root)) for p in Path(root).rglob('*')
                      if p.is_file()) != expected]


def summaries(text):
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    return [dict(zip(['tests', 'assertions', 'failures', 'errors'], map(int, values)))
            for values in re.findall(r'^Ran (\d+) tests containing (\d+) assertions\.\s*'
                                     r'(\d+) failures, (\d+) errors\.', text, re.MULTILINE)]


def main():
    began = time.monotonic()
    started = utc()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_label')
    args = parser.parse_args()
    assert LABEL.fullmatch(args.run_label), 'Invalid fresh run label'
    out = HERE / 'runs' / args.run_label
    out.mkdir(parents=True, exist_ok=False)
    work_deadline = began + WORK_SECONDS
    total_deadline = began + TOTAL_SECONDS
    stages = []
    error = None
    pins = None
    preparation = None
    trees = {}
    bundle = None
    classification = 'not-started'
    boot_id = (PROC / 'sys/kernel/random/boot_id').read_text().strip()

    def interrupt(_number, _frame):
        raise InterruptedError('Supervisor interrupted; clean owned children, never retry')

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)

    def stage(name, argv, env):
        folder = out / name
        folder.mkdir()
        journal = folder / 'ownership.jsonl'
        journal.touch(exist_ok=False)
        child = None
        primary = None
        observations = {}
        history = []
        faults = []
        unknown = []
        failure = None
        cleanup = []
        rc = None
        stage_started = time.monotonic()

        def record(event):
            with journal.open('a', encoding='utf-8') as stream:
                json.dump(dict(event, at=utc(), elapsed_s=time.monotonic()-began), stream)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())

        def attempt(label, function, default=None):
            try:
                return function()
            except BaseException as problem:
                faults.append({'stage': label, **error_info(problem)})
                return default

        def observe(pid):
            item = identity(pid)
            if item is None:
                return None
            key = (pid, item['starttime_ticks'])
            if observations.get(key) != item:
                record({'event': 'identity', 'identity': item})
                history.append(item.copy())
                observations[key] = item
            try:
                descendants = (PROC / str(pid) / 'task' / str(pid) / 'children').read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                descendants = []
            for descendant in descendants:
                observe(int(descendant))
            return item

        def scan():
            result = attempt('scan-owned-group', lambda: group_members(child.pid),
                             {'members': [], 'unreadable': [{'reason': 'group scan failed'}]})
            for entry in result['unreadable']:
                if entry not in unknown:
                    unknown.append(entry)
            for entry in result['members']:
                attempt('observe-group-member', lambda pid=entry['pid']: observe(pid))
            return result['members']

        def signal_owned(number):
            now = membership(child.pid)
            if now and primary and now['starttime_ticks'] != primary['starttime_ticks']:
                raise RuntimeError('Primary PID reused; refuse group signal')
            if primary is None and child.poll() is not None:
                raise RuntimeError('Missing primary identity after exit; refuse group signal')
            try:
                os.killpg(child.pid, number)
                cleanup.append(number.name)
                record({'event': 'signal-group', 'pgid': child.pid, 'signal': number.name})
            except ProcessLookupError:
                pass

        save(folder/'command.json', {'argv': argv, 'cwd': str(ROOT), 'at': utc(), 'boot_id': boot_id,
             'shared_work_remaining_s': max(0.0, work_deadline-time.monotonic()),
             'shared_total_remaining_s': max(0.0, total_deadline-time.monotonic())})
        try:
            assert time.monotonic() < work_deadline, 'Shared work budget exhausted before spawn'
            assert not changed(pins), 'Protected source/dependency drift before stage'
            assert not changed_trees(trees), 'Protected source file-set drift before stage'
            with (folder/'stdout.log').open('xb') as stdout, (folder/'stderr.log').open('xb') as stderr:
                assert time.monotonic() < work_deadline, 'Shared work budget exhausted during stage preflight'
                child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                         stdout=stdout, stderr=stderr, start_new_session=True)
                record({'event': 'spawn', 'pid': child.pid, 'expected_pgid': child.pid})
                primary = identity(child.pid)
                assert primary and primary['pgid'] == child.pid, 'Owned primary identity unavailable'
                save(folder/'primary-identity.json', dict(primary, boot_id=boot_id))
                observe(child.pid)
                while child.poll() is None:
                    observe(child.pid)
                    if time.monotonic() >= work_deadline:
                        raise TimeoutError('Shared 280s work deadline exceeded')
                    time.sleep(min(0.1, max(0.0, work_deadline-time.monotonic())))
                rc = child.wait()
                if time.monotonic() >= work_deadline:
                    raise TimeoutError('Late child result after shared work deadline')
        except BaseException as problem:
            failure = error_info(problem)
        finally:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            live = []
            survivors = []
            if child is not None:
                attempt('observe-before-cleanup', lambda: observe(child.pid))
                live = scan()
                if child.poll() is None or live:
                    # Unexpected leftover children make the stage unsuccessful even if killed.
                    if failure is None:
                        failure = {'type': 'LingeringChildren', 'message': 'Owned descendants outlived stage primary'}
                    attempt('terminate-group', lambda: signal_owned(signal.SIGTERM))
                    until = min(total_deadline-5.0, time.monotonic()+12.0)
                    while time.monotonic() < until and scan():
                        child.poll()
                        time.sleep(0.05)
                    if scan() or child.poll() is None:
                        attempt('kill-group', lambda: signal_owned(signal.SIGKILL))
                rc = attempt('reap-primary', lambda: child.wait(timeout=max(0.001,total_deadline-time.monotonic())),rc)
                live = scan()
                for pid, start in observations:
                    now = attempt('check-observed-identity', lambda pid=pid: membership(pid))
                    if now and now['starttime_ticks'] == start:
                        survivors.append(now)
            attempt('record-cleanup', lambda: record({'event':'cleanup','exit_code':rc,'remaining_group':live,
                    'remaining_observed':survivors,'membership_unknown':unknown,'cleanup_errors':list(faults)}))
            result = {'name':name,'exit_code':rc,'error':failure,'elapsed_s':time.monotonic()-stage_started,
                      'primary_identity':primary,'primary_reaped':bool(child and child.returncode is not None),
                      'observed_identities':history,'remaining_group':live,'remaining_observed':survivors,
                      'membership_unknown':unknown,'cleanup_errors':faults,'cleanup_signals':cleanup,
                      'within_total_deadline':time.monotonic()<total_deadline,
                      'artifacts':{q.name:digest(q) for q in folder.iterdir() if q.is_file()}}
            result['closed'] = bool(result['primary_reaped'] and not failure and not live and not survivors
                                    and not faults and not unknown and result['within_total_deadline'])
            save(folder/'execution.json',result)
            stages.append(result)
            signal.signal(signal.SIGINT, interrupt)
            signal.signal(signal.SIGTERM, interrupt)
        if not result['closed']:
            raise RuntimeError(name+' did not close successfully; no next stage')
        return rc

    try:
        preparation = json.loads((HERE/'preparation-hashes.json').read_text())
        assert all(digest(HERE/k)==v for k,v in preparation.items()), 'Preparation drift'
        pinned = json.loads((HERE/'source-pins.json').read_text())
        pins = pinned['files']
        trees = pinned['file_sets']
        assert not changed(pins), 'Protected source/dependency drift'
        assert not changed_trees(trees), 'Protected source file-set drift'
        assert not (ROOT/'dist/test.cjs').exists(), 'Pre-existing test bundle; refuse stale execution'
        assert not (ROOT/'.shadow-cljs').exists(), 'Unexpected project compiler state before first RED'
        assert not (Path.home()/'.shadow-cljs/config.edn').exists(), 'Unreviewed Shadow user configuration'
        env = os.environ.copy()
        remove = ['JAVA_OPTS','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS',
                  'CLJ_JVM_OPTS','JVM_OPTS','NODE_OPTIONS','NODE_PATH','XDG_CONFIG_HOME','LOCALAPPDATA']
        present = [key for key in remove if key in env]
        for key in remove:
            env.pop(key,None)
        env['JAVA_TOOL_OPTIONS'] = JVM_OPTIONS
        env['PATH'] = str(NODE.parent)+':'+str(JAVA.parent)+':'+env.get('PATH','')
        env['CI'] = 'true'
        env['npm_config_ignore_scripts'] = 'true'
        save(out/'environment-contract.json',{'removed_inherited_keys':present,'all_removed_candidates':remove,
             'new_JAVA_TOOL_OPTIONS':JVM_OPTIONS,'node':str(NODE),'java':str(JAVA),
             'force_spawn':True,'user_config_absent':True,'boot_id':boot_id})
        compile_argv = [str(NODE),str(ROOT/'node_modules/shadow-cljs/cli/runner.js'),
                        '--force-spawn','compile','test']
        compile_rc = stage('compile',compile_argv,env)
        if compile_rc != 0:
            classification = 'compile-failed-not-meaningful-red'
            raise RuntimeError('Compilation exited '+str(compile_rc)+'; explicit test stage not started')
        assert (ROOT/'dist/test.cjs').is_file() and (ROOT/'dist/test.cjs').stat().st_size>0, 'Compile produced no test bundle'
        compile_text=(out/'compile/stdout.log').read_text(errors='replace')+(out/'compile/stderr.log').read_text(errors='replace')
        assert '[:test] Build completed.' in compile_text, 'Missing actual compile completion marker'
        bundle = {'path':'dist/test.cjs','sha256':digest(ROOT/'dist/test.cjs'),'bytes':(ROOT/'dist/test.cjs').stat().st_size}
        save(out/'generated-test-bundle.json',bundle)
        test_rc = stage('explicit-node-test',[str(NODE),str(ROOT/'dist/test.cjs')],env)
        assert digest(ROOT/'dist/test.cjs')==bundle['sha256'], 'Generated bundle changed during test execution'
        actual=summaries((out/'explicit-node-test/stdout.log').read_text(errors='replace'))
        save(out/'test-summaries.json',{'explicit_node':actual,'compile_autorun':summaries(compile_text)})
        assert len(actual)==1 and actual[0]['tests']>0 and actual[0]['assertions']>0, 'Missing/nonunique completed explicit Node test summary'
        counts=actual[0]
        if counts['errors']:
            classification='test-errors-not-meaningful-red'
        elif counts['failures'] and test_rc!=0:
            classification='assertion-failures-root-review-required'
        elif counts['failures']:
            classification='test-exit-propagation-failure'
        elif test_rc==0:
            classification='unexpected-green-root-review-required'
        else:
            classification='nonzero-exit-without-assertion-failures'
    except BaseException as problem:
        error=error_info(problem)
        if classification=='not-started':
            classification='incomplete-or-preflight-failed-not-meaningful-red'
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        verification_errors=[]
        source_changed=[]
        tree_changed=[]
        prep_changed=[]
        for name, check in [('source', lambda: changed(pins) if pins else []),
                            ('file_sets', lambda: changed_trees(trees)),
                            ('preparation', lambda: [k for k,v in preparation.items()
                             if not (HERE/k).is_file() or digest(HERE/k)!=v] if preparation else [])]:
            try:
                found=check()
                if name=='source':
                    source_changed=found
                elif name=='file_sets':
                    tree_changed=found
                else:
                    prep_changed=found
            except BaseException as problem:
                verification_errors.append({'stage':name,**error_info(problem)})
        elapsed=time.monotonic()-began
        result={'started_utc':started,'ended_utc':utc(),'elapsed_s':elapsed,'work_s':WORK_SECONDS,
                'total_s':TOTAL_SECONDS,'total_deadline_exceeded':elapsed>=TOTAL_SECONDS,'error':error,
                'classification':classification,'stages':stages,'source_changed':source_changed,
                'source_file_sets_changed':tree_changed,'preparation_changed':prep_changed,
                'verification_errors':verification_errors,'boot_id':boot_id,'test_bundle':bundle,
                'limits':['Assertion failures need root review against intended design tests; this wrapper cannot grant meaningful RED.',
                          'Shadow autorun may itself run tests; explicit Node output and exit are captured separately.',
                          'Polling may miss brief children. OS/filesystem stalls can delay enforcement or prevent final persistence.']}
        result['execution_closed']=bool(error is None and len(stages)==2 and all(x['closed'] for x in stages)
                                        and not source_changed and not tree_changed and not prep_changed
                                        and not verification_errors and elapsed<TOTAL_SECONDS)
        save(out/'execution.json',result)
        print(json.dumps({k:result[k] for k in ['execution_closed','classification','elapsed_s','error','source_changed']}))
    return stages[-1]['exit_code'] if result['execution_closed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
