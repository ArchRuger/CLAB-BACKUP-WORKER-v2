"""Network design engine: runs the pinned `netlab` CLI as a child process in a private per-job
working directory and reads back its data-only outputs. This is the only module that runs `netlab`
or imports `netsim`; every other feature module stays on the containerlab/device paths it already has.

Observed against networklab 26.9 (`netlab version 26.09`) in this checkout, scratch runs under
/tmp/claude-1000/design-engine-scratch:
  - `netlab create -p external -o config -o yaml=transformed.yaml topology.yml` exits 0 on success. It
    deletes and recreates `node_files/` under the *current working directory* and writes one file per
    node and module at `node_files/<node>/<module-or-normalize-or-initial>` (no extension), plus
    `transformed.yaml`. Progress ("[CONFIG]  <node>: normalize,initial,ospf") goes to stdout, not stderr.
  - Every observed engine failure exits 1: an unsupported module on a device, an unknown device
    identifier, an unknown module name and a YAML syntax error in the topology all exit 1. For a topology
    that netlab can parse but not process, stderr carries, in order: an optional header line
    'Errors encountered while processing topology.yml', one or more lines of the shape
    '<ErrorClass> in <area>: <message>' (ErrorClass one of IncorrectValue, IncorrectAttr, IncorrectType,
    MissingValue, MissingDependency, FatalError -- see netsim/utils/log.py err_class_map) each optionally
    followed by indented '... ' hint lines, and a final 'Fatal error in netlab: Cannot proceed beyond
    this point due to errors, exiting' line. A YAML syntax error skips straight to a single
    'Fatal error in netlab: Cannot read YAML from <path>: ...' line with no header and no class line.
  - netlab keeps a per-HOME cache (`~/.netlab/stats.json[.lock]`, `~/.netlab/topology-defaults.pickle`)
    and, unless told otherwise, updates usage-statistics counters (netsim/utils/stats.py) on every run.
    Pre-seeding `home/.netlab/stats.json` with `{"_disabled": true}` before the child runs is netlab's
    own supported opt-out (`write_stats()` returns immediately when `_disabled` is set; `netlab usage
    stop` sets the same flag) and was confirmed live to leave the file byte-for-byte unchanged after a
    successful run. `netsim/utils/stats.py` does no network I/O of its own (file and `filelock` only).
  - `netlab version` prints `netlab version 26.09` as its first line and exits 0; the distribution metadata
    spells the same release `26.9` (engine_status() reports the latter without starting a process).
"""
import importlib.metadata
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

import yaml

ENGINE_TIMEOUT = 120          # seconds, wall clock, for one generation
OUTPUT_LIMIT = 256 * 1024     # bytes of stdout/stderr kept
ARTIFACT_LIMIT = 1024 * 1024  # bytes per generated configuration file
TOTAL_ARTIFACT_LIMIT = 16 * 1024 * 1024
TRANSFORMED_LIMIT = 8 * 1024 * 1024
ARGV = ('netlab', 'create', '-p', 'external', '-o', 'config', '-o', 'yaml=transformed.yaml', 'topology.yml')

NOT_INSTALLED = 'The network design engine (netlab) is not installed in this manager image.'
NO_DISTRIBUTION = 'The network design engine (netlab) binary exists but its networklab distribution is missing from this image.'
UNEXPECTED_VERSION = 'The network design engine (netlab) reports an unexpected version.'
TIMED_OUT = 'The network design engine did not finish in time.'
SIZE_EXCEEDED = 'A generated configuration exceeds the size limit.'
TRANSFORMED_TOO_LARGE = 'The transformed topology exceeds the size limit.'
COULD_NOT_START = 'The network design engine could not be started.'

# Stderr lines that name one of netlab's own error classes, or its final abort line, or the header
# it prints before the first class line. Continuation/hint lines (indented '... ') never match.
_ERROR_LINE = re.compile(
    r'^(?:Errors encountered while processing\b'
    r'|Fatal error in \S+:'
    r'|(?:IncorrectValue|IncorrectAttr|IncorrectType|MissingValue|MissingDependency|FatalError)\b.*:)')


class EngineError(Exception):
    """A controlled, user-facing reason; never raw engine output."""


class _ArtifactTooLarge(Exception):
    pass


def engine_status():
    """{'available': bool, 'version': '26.9' or '', 'path': '/usr/local/bin/netlab' or '', 'diagnostic': ''}.
    Answered from the installed distribution's metadata and the binary on PATH, without starting a process:
    `netlab version` would run with the caller's environment and HOME (writing usage counters and a defaults
    cache there), which is exactly what the private per-job environment of run_generation avoids. A missing
    binary or a missing distribution gives available False with a precise, feature-specific diagnostic. Never
    raises."""
    path = shutil.which('netlab')
    if not path:
        return {'available': False, 'version': '', 'path': '', 'diagnostic': NOT_INSTALLED}
    try:
        version = importlib.metadata.version('networklab')
    except importlib.metadata.PackageNotFoundError:
        return {'available': False, 'version': '', 'path': path, 'diagnostic': NO_DISTRIBUTION}
    if not re.fullmatch(r'\d+(\.\d+)+', version or ''):
        return {'available': False, 'version': '', 'path': path, 'diagnostic': UNEXPECTED_VERSION}
    return {'available': True, 'version': version, 'path': path, 'diagnostic': ''}


def _drain(stream, limit, sink):
    """Read a pipe to EOF on its own thread, keeping only the last `limit` bytes."""
    tail = bytearray()
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            tail.extend(chunk)
            if len(tail) > limit * 2:
                del tail[:-limit]
    except Exception:
        pass
    finally:
        sink['data'] = bytes(tail[-limit:])
        try:
            stream.close()
        except Exception:
            pass


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


_EXCEPTION_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\b')
UNEXPECTED_FAILURE = 'The network design engine failed unexpectedly on a value it could not process'


def _error_lines(stderr_text):
    """netlab's own class-tagged lines; when it crashed instead (a Python traceback), one controlled line
    naming the exception class only, never a path or a message from the traceback."""
    lines = [line[:500] for line in stderr_text.splitlines() if _ERROR_LINE.match(line)]
    if lines: return lines
    tail = [line for line in stderr_text.splitlines() if line.strip()]
    match = _EXCEPTION_LINE.match(tail[-1]) if tail else None
    if match or any(line.startswith('Traceback') for line in tail):
        return [UNEXPECTED_FAILURE + (' (' + match.group(1) + ').' if match else '.')]
    return lines


def _node_file_order(node_dir, module_list):
    """normalize (if present), then initial, then `module_list` in order, then any remaining files
    sorted -- the data-derived rule netsim/outputs/config.py writes files by."""
    remaining = set(os.listdir(node_dir))
    order = []
    for fixed in ('normalize', 'initial'):
        if fixed in remaining:
            order.append(fixed)
            remaining.discard(fixed)
    for module in module_list:
        if module in remaining:
            order.append(module)
            remaining.discard(module)
    order.extend(sorted(remaining))
    return order


def _load_artifacts(node_files_dir, transformed):
    nodes = transformed.get('nodes')
    nodes = nodes if isinstance(nodes, dict) else {}
    node_names = list(nodes.keys())
    for extra in sorted(os.listdir(node_files_dir)):
        if extra not in node_names:
            node_names.append(extra)
    artifacts = {}
    total = 0
    for name in node_names:
        node_dir = os.path.join(node_files_dir, name)
        if not os.path.isdir(node_dir):
            continue
        info = nodes.get(name)
        module_list = info.get('module') if isinstance(info, dict) else None
        module_list = module_list if isinstance(module_list, list) else []
        entries = []
        for filename in _node_file_order(node_dir, module_list):
            path = os.path.join(node_dir, filename)
            size = os.path.getsize(path)
            if size > ARTIFACT_LIMIT:
                raise _ArtifactTooLarge()
            total += size
            if total > TOTAL_ARTIFACT_LIMIT:
                raise _ArtifactTooLarge()
            with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                entries.append((filename, handle.read()))
        artifacts[name] = entries
    return artifacts


def run_generation(work_root, topology, *, timeout=ENGINE_TIMEOUT, stopping=None):
    """Generate configurations for one netlab topology (a plain dict built by the adapter, never user text).
    Creates work_root/<uuid4 hex>/ (mode 0o700) with home/ inside it, writes topology.yml with yaml.safe_dump
    (sort_keys=False, default_flow_style=False), runs ARGV with cwd = that directory, HOME = its home/,
    LANG=C.UTF-8, PATH = the parent's PATH, PYTHONDONTWRITEBYTECODE=1, and NOTHING else in the
    environment (in particular no NETLAB_* variable: netlab turns every NETLAB_* variable into a topology
    default). Before the child starts, home/.netlab/ (0o700) is created with home/.netlab/stats.json
    (0o600) containing exactly {"_disabled": true} -- netlab's own supported opt-out for its usage
    statistics -- so the child never writes counters. stdin is closed (DEVNULL). The child runs in its own
    process group / session (start_new_session=True) so a timeout kills the whole group (SIGKILL after
    SIGTERM); `stopping` is an optional threading.Event polled every 0.2 s that aborts the same way.
    stdout and stderr are read completely but only the last OUTPUT_LIMIT bytes of each are kept.
    Returns a dict:
      ok: bool (exit code 0 and the outputs read)
      exit_code: int or None (None when killed)
      errors: list[str] of the engine's own error lines (stderr lines that start with a netlab error class
              such as 'IncorrectValue in modules: ...', 'IncorrectAttr in nodes: ...', 'Errors encountered
              while processing ...', 'Fatal error in netlab: ...'), each cut to 500 characters
      stderr_tail: str (last 4000 characters, for the job record only, never for the UI)
      duration: float seconds
      engine_version: str from the transformed topology's `_netlab_version` when present
      transformed: dict (yaml.safe_load of transformed.yaml, only when ok) or {}
      artifacts: {node_name: [(module, text), ...]} in netlab's own order (see _node_file_order), only
                 when ok
      workdir: the job directory path (the caller removes it; run_generation does not)
    Raises EngineError only for a caller error (work_root missing or not a directory, topology not a dict);
    every engine failure is reported in the result."""
    if not os.path.isdir(work_root):
        raise EngineError('The network design work directory does not exist.')
    if not isinstance(topology, dict):
        raise EngineError('The network topology must be a plain document.')

    jobdir = os.path.join(work_root, uuid.uuid4().hex)
    home = os.path.join(jobdir, 'home')
    netlab_home = os.path.join(home, '.netlab')
    os.mkdir(jobdir, 0o700)
    os.mkdir(home, 0o700)
    os.mkdir(netlab_home, 0o700)
    stats_path = os.path.join(netlab_home, 'stats.json')
    with open(stats_path, 'w', encoding='utf-8') as handle:
        handle.write('{"_disabled": true}')
    os.chmod(stats_path, 0o600)

    topology_path = os.path.join(jobdir, 'topology.yml')
    with open(topology_path, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(topology, handle, sort_keys=False, default_flow_style=False)

    env = {'PATH': os.environ.get('PATH', ''), 'HOME': home, 'LANG': 'C.UTF-8',
           'PYTHONDONTWRITEBYTECODE': '1'}

    result = {'ok': False, 'exit_code': None, 'errors': [], 'stderr_tail': '', 'duration': 0.0,
              'engine_version': '', 'transformed': {}, 'artifacts': {}, 'workdir': jobdir}

    started = time.monotonic()
    try:
        process = subprocess.Popen(list(ARGV), cwd=jobdir, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
    except OSError:
        result['duration'] = time.monotonic() - started
        result['errors'] = [COULD_NOT_START]
        return result

    out_sink, err_sink = {}, {}
    out_thread = threading.Thread(target=_drain, args=(process.stdout, OUTPUT_LIMIT, out_sink), daemon=True)
    err_thread = threading.Thread(target=_drain, args=(process.stderr, OUTPUT_LIMIT, err_sink), daemon=True)
    out_thread.start()
    err_thread.start()

    deadline = started + timeout
    killed = False
    exit_code = None
    while True:
        try:
            exit_code = process.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() > deadline or (stopping is not None and stopping.is_set()):
                killed = True
                break
    if killed:
        _kill_group(process)
        exit_code = None

    out_thread.join(timeout=5)
    err_thread.join(timeout=5)
    result['duration'] = time.monotonic() - started
    stderr_text = err_sink.get('data', b'').decode('utf-8', errors='replace')
    result['stderr_tail'] = stderr_text[-4000:]

    if killed:
        result['errors'] = [TIMED_OUT]
        return result

    result['exit_code'] = exit_code
    if exit_code != 0:
        result['errors'] = _error_lines(stderr_text)
        return result

    transformed_path = os.path.join(jobdir, 'transformed.yaml')
    node_files_dir = os.path.join(jobdir, 'node_files')
    try:
        if os.path.getsize(transformed_path) > TRANSFORMED_LIMIT:
            result['errors'] = [TRANSFORMED_TOO_LARGE]
            return result
        with open(transformed_path, 'r', encoding='utf-8') as handle:
            transformed = yaml.safe_load(handle) or {}
        if not isinstance(transformed, dict):
            transformed = {}
        artifacts = _load_artifacts(node_files_dir, transformed)
    except _ArtifactTooLarge:
        result['errors'] = [SIZE_EXCEEDED]
        return result
    except (OSError, yaml.YAMLError):
        result['errors'] = ['The network design engine finished but its output could not be read.']
        return result

    result['transformed'] = transformed
    result['artifacts'] = artifacts
    result['engine_version'] = transformed.get('_netlab_version', '') if isinstance(
        transformed.get('_netlab_version', ''), str) else ''
    result['ok'] = True
    return result
