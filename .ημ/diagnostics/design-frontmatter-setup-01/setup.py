"""One source-bootstrap and ignore-scripts package-install attempt; no JVM gates."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NODE = Path('/home/err/.volta/tools/image/node/22.20.0/bin/node')
PNPM = Path('/home/err/.volta/tools/image/packages/pnpm/lib/node_modules/pnpm/bin/pnpm.cjs')
ETA = '0ed56aa74a53a1d1e9c2e55ce95451817a7f3a90'
CHAT = '86385532b4f8606946555d0ada8e3fb22f35b4c3'


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def member(pid):
    try:
        fields = Path('/proc', str(pid), 'stat').read_text().rsplit(') ', 1)[1].split()
        return dict(pid=pid, state=fields[0], pgid=int(fields[2]), starttime_ticks=int(fields[19]))
    except (FileNotFoundError, ProcessLookupError):
        return None


def members(pgid):
    owned, unknown = [], []
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            try:
                item = member(int(path.name))
                if item and item['pgid'] == pgid:
                    owned.append(item)
            except (OSError, ValueError, IndexError) as error:
                unknown.append(dict(pid=int(path.name), error=repr(error)))
    return owned, unknown


def bounded(label, argv, cwd, env, work=110.0, total=120.0):
    directory = HERE / label
    directory.mkdir()
    begun = time.monotonic()
    deadline = begun + total
    observed, errors = {}, []
    child = None
    error = None
    unknown = []
    save(directory / 'command.json', dict(argv=argv, cwd=str(cwd), at=utc(), work_s=work,
                                         total_s=total, lifecycle_scripts=False))
    with (directory / 'stdout.log').open('xb') as out, (directory / 'stderr.log').open('xb') as err, \
            (directory / 'ownership.jsonl').open('x', encoding='utf-8') as journal:
        def event(value):
            journal.write(json.dumps(dict(at=utc(), elapsed_s=time.monotonic()-begun, **value))+'\n')
            journal.flush()
            os.fsync(journal.fileno())

        def observe():
            current, unreadable = members(child.pid)
            unknown[:] = unreadable
            for item in current:
                key = (item['pid'], item['starttime_ticks'])
                if key not in observed:
                    for field in ['exe', 'cwd']:
                        try:
                            item[field] = os.readlink(Path('/proc', str(item['pid']), field))
                        except OSError as problem:
                            item[field] = None
                            item[field+'_error'] = repr(problem)
                    observed[key] = item
                    event(dict(event='identity', identity=item))
                    if Path(item.get('exe') or '').name == 'java':
                        raise RuntimeError('Unexpected owned Java process; setup is not authorized to invoke JVM')
            return current

        try:
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, start_new_session=True)
            event(dict(event='spawn', pid=child.pid, expected_pgid=child.pid))
            initial = member(child.pid)
            save(directory / 'primary-identity.json', dict(at=utc(), pid=child.pid,
                 expected_pgid=child.pid, identity=initial))
            while child.poll() is None:
                observe()
                if time.monotonic() >= begun+work:
                    raise TimeoutError('Work deadline exceeded; no retry')
                time.sleep(0.1)
            child.wait()
            if time.monotonic() > begun+work:
                raise TimeoutError('Child completion observed after work deadline')
            if child.returncode:
                raise RuntimeError('Command failed: exit '+str(child.returncode))
        except BaseException as problem:
            error = repr(problem)
        finally:
            if child is not None:
                try:
                    current = observe()
                    for sig, grace in [(signal.SIGTERM, 3.0), (signal.SIGKILL, 6.0)]:
                        if current:
                            # Identity came from stat and is still in this owned process group.
                            os.killpg(child.pid, sig)
                            event(dict(event='signal', pgid=child.pid, signal=sig.name))
                        until = min(deadline, time.monotonic()+grace)
                        while time.monotonic() < until:
                            child.poll()
                            current = observe()
                            if not current:
                                break
                            time.sleep(min(0.1, max(0.0, until-time.monotonic())))
                    if child.poll() is None:
                        child.wait(timeout=max(0.001, deadline-time.monotonic()))
                    event(dict(event='primary-reaped', pid=child.pid, exit_code=child.returncode))
                except BaseException as problem:
                    errors.append(repr(problem))
            remaining, unknown = members(child.pid) if child else ([], [])
            survivors = [now for key in observed if (now := member(key[0])) and now['starttime_ticks']==key[1]]
            elapsed = time.monotonic()-begun
            complete = bool(child and child.returncode == 0 and not error and not errors
                            and not remaining and not survivors and not unknown and elapsed <= total)
            result = dict(at=utc(), status='complete' if complete else 'failed', error=error,
                          elapsed_s=elapsed, exit_code=child.returncode if child else None,
                          primary_reaped=bool(child and child.returncode is not None),
                          observed_identities=list(observed.values()), remaining_group=remaining,
                          remaining_observed=survivors, membership_unknown=unknown, cleanup_errors=errors,
                          total_deadline_exceeded=elapsed>total,
                          limit='Polling can miss brief children. Stat controls membership. OS/I/O stalls cannot be forcibly time-bounded.')
            save(directory / 'result.json', result)
    if not complete:
        raise RuntimeError(label+' failed; see immutable result/logs')
    return result


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          timeout=15, stdin=subprocess.DEVNULL).stdout


def copy_tree(repo, commit, tree, target):
    assert not target.exists(), 'Refuse to replace existing source directory'
    assert git(repo, 'cat-file', '-t', commit).strip()==b'commit'
    commit_bytes=git(repo, 'cat-file', 'commit', commit)
    assert hashlib.sha1(b'commit '+str(len(commit_bytes)).encode()+b'\0'+commit_bytes).hexdigest()==commit
    listing=git(repo, 'ls-tree', '-r', '-z', commit, tree)
    records=[]
    for entry in listing.split(b'\0'):
        if not entry:
            continue
        metadata,name=entry.split(b'\t',1)
        mode,kind,oid=metadata.decode().split()
        assert kind=='blob' and mode in ['100644','100755'], (mode,kind)
        relative=Path(name.decode()).relative_to(tree)
        assert '..' not in relative.parts and not relative.is_absolute()
        data=git(repo, 'cat-file', 'blob', oid)
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==oid
        output=target/relative
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            stream.write(data)
        output.chmod(0o755 if mode=='100755' else 0o644)
        records.append(dict(path=str(relative), bytes=len(data), git_blob=oid, mode=mode, sha256=digest(output)))
    assert records
    assert {str(x.relative_to(target)) for x in target.rglob('*') if x.is_file()}=={x['path'] for x in records}
    return dict(commit=commit, tree=tree, tree_object=git(repo,'rev-parse',commit+':'+tree).decode().strip(),
                target=str(target.relative_to(ROOT)), files=records, count=len(records),
                bytes=sum(x['bytes'] for x in records), copied_from='verified Git blobs, not ambient cache')


def main():
    prep=json.loads((ROOT/'.ημ/diagnostics/design-frontmatter-red/preparation.json').read_text())
    protected={x['path']:x['sha256'] for x in prep['tests']+prep['protected_head_files']}
    protected.update({str(x.relative_to(ROOT)):digest(x) for x in (ROOT/'.ημ').rglob('*')
                      if x.is_file() and not x.is_relative_to(HERE)})
    save(HERE/'before.json',dict(at=utc(), protected=protected, setup_source_sha256=digest(Path(__file__))))
    assert all(digest(ROOT/k)==v for k,v in protected.items())
    assert not (ROOT/'node_modules').exists()
    env=os.environ.copy()
    removed=[key for key in ['JAVA_OPTS','JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS','NODE_OPTIONS'] if key in env]
    for key in ['JAVA_OPTS','JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS','NODE_OPTIONS']:
        env.pop(key,None)
    env.update(PATH=str(NODE.parent)+':'+env.get('PATH',''), CI='true',
               npm_config_ignore_scripts='true', npm_config_lockfile='false')
    save(HERE/'environment-contract.json',dict(node=str(NODE),node_sha256=digest(NODE),
         pnpm_js=str(PNPM),pnpm_sha256=digest(PNPM),removed_option_keys=removed,
         ignore_scripts=True,lockfile=False,no_jvm_build_test_classpath_command=True))
    summary=dict(at=utc(), sources=[], error=None)
    try:
        with tempfile.TemporaryDirectory(prefix='rheos-design-source-') as temporary:
            checkout=Path(temporary)/'chat-ui'
            checkout.mkdir()
            git(checkout,'init','--quiet')
            bounded('chat-source-fetch', ['git','-c','core.hooksPath=/dev/null','-C',str(checkout),
                    'fetch','--no-tags','--depth=1','https://github.com/open-hax/chat-ui.git',CHAT],
                    ROOT,env,work=80,total=90)
            assert git(checkout,'rev-parse','FETCH_HEAD').decode().strip()==CHAT
            summary['sources'].append(copy_tree(Path('/home/err/spaces/foresight/eta-mu'),ETA,
                    'packages/protocols/src',ROOT/'deps/protocols/src'))
            summary['sources'].append(copy_tree(checkout,CHAT,'src',ROOT/'deps/chat-ui/src'))
        save(HERE/'source-dependencies.json',dict(at=utc(),sources=summary['sources'],temporary_checkout_removed=True))
        bounded('bootstrap-verification', ['bash','--noprofile','--norc',str(ROOT/'scripts/bootstrap-source-deps.sh')],ROOT,env,work=10,total=20)
        bounded('node-version',[str(NODE),'--version'],ROOT,env,work=5,total=10)
        assert (HERE/'node-version/stdout.log').read_text().strip()=='v22.20.0'
        bounded('pnpm-version',[str(NODE),str(PNPM),'--version'],ROOT,env,work=5,total=10)
        summary['install']=bounded('install',[str(NODE),str(PNPM),'install','--ignore-scripts','--lockfile=false'],ROOT,env)
    except BaseException as problem:
        summary['error']=repr(problem)
    finally:
        summary['ended_at']=utc()
        summary['protected_changed']=[k for k,v in protected.items() if not (ROOT/k).is_file() or digest(ROOT/k)!=v]
        summary['sources_postverified']=all(digest(ROOT/s['target']/x['path'])==x['sha256'] for s in summary['sources'] for x in s['files'])
        summary['no_jvm_gate_invoked']=True
        summary['qualification']='Dependency preparation only, not compile/test/build qualification; lifecycle scripts explicitly disabled.'
        summary['status']='complete' if not summary['error'] and not summary['protected_changed'] and summary['sources_postverified'] else 'failed'
        save(HERE/'result.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['sources','install']}))
    return 0 if summary['status']=='complete' else 1


if __name__=='__main__':
    raise SystemExit(main())
