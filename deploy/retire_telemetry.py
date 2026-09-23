"""Undo deploy/setup-telemetry.sh: remove the retired Grafana/Prometheus stack.

Ownership is verified only by the Compose project label ``com.docker.compose.project=
clab-manager-telemetry``; a container merely named ``clab-manager-grafana`` without that
label is reported and left alone, and nothing outside that label is ever touched. Every
step is idempotent: a VM that never installed the stack, or one that was already
retired, reports nothing to do and exits 0.

Only two on-disk locations are ever touched: ``DATA_ROOT/telemetry`` (the old
TELEMETRY_CONFIG_DIR default) and ``DATA_ROOT/data/telemetry`` (the folder that held the
old TELEMETRY_MAPS_DIR default). The old setup always wrote there; a ``.env`` that names a
*different* TELEMETRY_CONFIG_DIR or TELEMETRY_MAPS_DIR never worked in the first place, so
that value is reported and left alone rather than acted on. Each of the two fixed paths is
also required to need no dereferencing (``path.resolve() == path``) and to have no symlink
anywhere between it and DATA_ROOT; a path that fails this is reported and left alone too,
never followed.

Everything is read and validated (docker discovery, the exact bytes of ``.env``, the safety
of the two fixed paths) before the first destructive step. ``.env`` is never evaluated as
shell code and is rewritten byte for byte: only whole ``TELEMETRY_*`` lines are removed
(their own original bytes, including line ending, archived first so a failed archive write
never loses them); every other line, including its exact line ending, is otherwise
untouched and stays in order.
"""
import datetime
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
PROJECT = 'clab-manager-telemetry'
LABEL_FILTER = f'label=com.docker.compose.project={PROJECT}'
# Pinned by deploy/compose.telemetry.yml (now removed); matched by digest only, never by tag.
IMAGES = (
    'prom/prometheus@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0',
    'grafana/grafana-oss@sha256:5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2',
)
# Overridable by tests only; the real root is fixed for every VM installation.
DATA_ROOT = '/srv/containerlab-node-manager'
# A whole line whose key starts with TELEMETRY_; matched on the raw bytes, never text-decoded
# first (str.splitlines()/bytes.splitlines() would also break lines on VT/FF/U+2028, corrupting
# an unrelated value that happens to contain one of those bytes).
KEY_PATTERN_BYTES = re.compile(rb'^\s*TELEMETRY_[A-Z0-9_]*\s*=')


class RetireError(ValueError):
    """A step that must stop the whole run with a clear, user-facing message."""


def fixed_config_dir():
    """The only path ever touched for TELEMETRY_CONFIG_DIR: what setup-telemetry.sh always used."""
    return Path(DATA_ROOT) / 'telemetry'


def fixed_maps_root():
    """The only path ever touched for TELEMETRY_MAPS_DIR: the folder that held the dashboards
    the manager generated (TELEMETRY_MAPS_DIR itself was DATA_ROOT/data/telemetry/dashboards;
    its parent is archived/removed as a whole, since nothing else lives under it)."""
    return Path(DATA_ROOT) / 'data' / 'telemetry'


def fixed_maps_leaf():
    return fixed_maps_root() / 'dashboards'


def run(runner, args, timeout=30):
    """A subprocess.run-shaped call: real docker/bash in production, a fake in tests."""
    return (runner or subprocess.run)(args, capture_output=True, text=True, timeout=timeout)


def command_text(result):
    return (result.stderr or result.stdout or '').strip()


def read_values(text):
    """Parse ``KEY=value`` lines without ever evaluating the file as shell. Informational only
    (used to report a TELEMETRY_CONFIG_DIR/TELEMETRY_MAPS_DIR override); the byte-exact rewrite
    of .env never goes through this."""
    values = {}
    for line in text.splitlines():
        match = re.match(r'^\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$', line)
        if match:
            values[match[1]] = match[2].strip().strip('"\'')
    return values


def split_env_lines(data):
    """Split `data` on b'\\n' only, each line keeping its own original terminator exactly
    (so CRLF survives, and a VT/FF/U+2028 byte inside a value is never treated as a break,
    unlike str.splitlines()/bytes.splitlines()). The last line keeps no terminator when the
    file does not end in one; a trailing newline never manifests as a spurious empty line."""
    parts = data.split(b'\n')
    lines = [part + b'\n' for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def read_env_bytes(env_path):
    """(exists, raw bytes). Raises RetireError, naming the file and the next step, if the file
    exists but cannot be read or is not valid UTF-8; never guesses at a broken file's content."""
    env_path = Path(env_path)
    if not env_path.exists():
        return False, b''
    if env_path.is_symlink():
        raise RetireError(f'{env_path} is a symlink; refusing to follow it. '
                          'Next: replace it with a plain file and rerun deploy/retire-telemetry.sh.')
    try:
        data = env_path.read_bytes()
    except OSError as error:
        raise RetireError(f'{env_path} could not be read: {error}. '
                          'Next: fix its permissions or ownership, then rerun deploy/retire-telemetry.sh.')
    try:
        data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise RetireError(f'{env_path} is not valid UTF-8: {error}. '
                          'Next: repair or restore the file by hand, then rerun deploy/retire-telemetry.sh.')
    return True, data


def note_env_override(values, key, fixed_path):
    """The old setup always wrote to the fixed path; a different value in .env never worked,
    so it is reported and left alone, never touched."""
    value = values.get(key)
    if not value:
        return
    try:
        same = Path(value) == fixed_path
    except (TypeError, ValueError):
        same = False
    if not same:
        print(f'{key} in .env names {value}; the installed stack always used {fixed_path}, so this run leaves that path alone.')


def path_is_plain(path):
    """True only if `path` needs no dereferencing at all (``path.resolve() == path``) and no
    component from DATA_ROOT down to the leaf is itself a symlink, checked explicitly by
    walking the parents (belt and suspenders alongside the resolve() comparison)."""
    try:
        if path.resolve() != path:
            return False
    except OSError:
        return False
    root = Path(DATA_ROOT)
    current = path
    while True:
        try:
            if current.is_symlink():
                return False
        except OSError:
            return False
        if current == root or current.parent == current:
            break
        current = current.parent
    return True


def discover_containers(runner):
    """[(id, name, service)] for containers carrying the project label; never matched by name."""
    result = run(runner, ['docker', 'ps', '-a', '--filter', LABEL_FILTER,
                          '--format', '{{.ID}} {{.Names}} {{.Label "com.docker.compose.service"}}'])
    if result.returncode != 0:
        raise RetireError('docker ps failed: ' + command_text(result))
    containers = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(' ', 2)
        containers.append((parts[0], parts[1] if len(parts) > 1 else '', parts[2] if len(parts) > 2 else ''))
    return containers


def discover_volumes(runner):
    result = run(runner, ['docker', 'volume', 'ls', '--filter', LABEL_FILTER, '--format', '{{.Name}}'])
    if result.returncode != 0:
        raise RetireError('docker volume ls failed: ' + command_text(result))
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def discover_networks(runner):
    result = run(runner, ['docker', 'network', 'ls', '--filter', LABEL_FILTER, '--format', '{{.Name}}'])
    if result.returncode != 0:
        raise RetireError('docker network ls failed: ' + command_text(result))
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def remove_containers(runner, containers, dry_run=False):
    for identifier, name, service in containers:
        label = name or identifier
        print(f'Container {label} ({service or "unlabelled service"}): ' + ('would remove' if dry_run else 'removing'))
        if dry_run:
            continue
        result = run(runner, ['docker', 'rm', '-f', identifier])
        if result.returncode != 0:
            raise RetireError(f'Removing container {label} failed: ' + command_text(result))


def remove_volumes(runner, volumes, dry_run=False):
    for name in volumes:
        print(f'Volume {name}: ' + ('would remove' if dry_run else 'removing'))
        if dry_run:
            continue
        result = run(runner, ['docker', 'volume', 'rm', name])
        if result.returncode != 0:
            raise RetireError(f'Removing volume {name} failed: ' + command_text(result))


def remove_networks(runner, networks, dry_run=False):
    for name in networks:
        print(f'Network {name}: ' + ('would remove' if dry_run else 'removing'))
        if dry_run:
            continue
        result = run(runner, ['docker', 'network', 'rm', name])
        if result.returncode != 0:
            raise RetireError(f'Removing network {name} failed: ' + command_text(result))


def remove_images(runner, containers, dry_run=False):
    """Remove the two pinned images by digest, but only when no other container uses them.

    The containers this run is itself removing (already reported above) never count as
    "still used": in a real run they are already gone by the time this is checked, and in
    a dry run they are excluded explicitly so the preview stays accurate.
    """
    labelled_ids = {identifier for identifier, _name, _service in containers}
    removed = []
    for image in IMAGES:
        used = run(runner, ['docker', 'ps', '-a', '-q', '--filter', f'ancestor={image}'])
        if used.returncode != 0:
            raise RetireError(f'Checking whether {image} is still in use failed: ' + command_text(used))
        other_users = [line for line in used.stdout.split() if line not in labelled_ids]
        if other_users:
            print(f'Image {image}: still used by another container; leaving it.')
            continue
        if dry_run:
            print(f'Image {image}: would remove if present.')
            continue
        result = run(runner, ['docker', 'image', 'rm', image])
        if result.returncode != 0:
            message = command_text(result)
            if 'no such image' in message.lower():
                print(f'Image {image}: not present.')
                continue
            raise RetireError(f'Removing image {image} failed: {message}')
        print(f'Image {image}: removed.')
        removed.append(image)
    return removed


def prepare_archive(stamp=None):
    stamp = stamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return Path(DATA_ROOT) / f'telemetry-retired-{stamp}'


def retire_directory(path, destination, purge, dry_run):
    """Move `path` under `destination`, or delete it with --purge. Returns True if it existed."""
    if not path.is_dir():
        print(f'{path}: not present.')
        return False
    if purge:
        print(f'{path}: ' + ('would delete' if dry_run else 'deleting'))
        if not dry_run:
            shutil.rmtree(path)
        return True
    print(f'{path}: ' + (f'would move to {destination}' if dry_run else f'moving to {destination}'))
    if not dry_run:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
    return True


def write_atomic_bytes(path, data, mode, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix='.retire-telemetry-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if hasattr(os, 'chown'):
            os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_env(env_path, env_exists, lines, archive, purge, dry_run):
    """Strip whole TELEMETRY_* lines from .env, keeping every other line byte for byte
    (including its own original line ending) and in order. The archive of removed lines is
    written and confirmed before .env itself is ever replaced, so a failed archive write
    never loses them; .env is left completely untouched in that case.
    """
    env_path = Path(env_path)
    if not env_exists:
        print(f'{env_path}: not present; nothing to update.')
        return False
    kept, removed = [], []
    for line in lines:
        if KEY_PATTERN_BYTES.match(line):
            removed.append(line)
        else:
            kept.append(line)
    if not removed:
        print(f'{env_path}: no TELEMETRY_* keys found.')
        return False
    print(f'{env_path}: ' + (f'would remove {len(removed)} TELEMETRY_* line(s)' if dry_run
                             else f'removing {len(removed)} TELEMETRY_* line(s)'))
    if dry_run:
        return True
    if not purge:
        archived_path = archive / 'env-telemetry.txt'
        archived_bytes = b'\n'.join(line.rstrip(b'\r\n') for line in removed) + b'\n'
        try:
            archive.mkdir(mode=0o700, parents=True, exist_ok=True)
            archived_path.write_bytes(archived_bytes)
            os.chmod(archived_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as error:
            raise RetireError(f'Could not archive the removed TELEMETRY_* lines to {archived_path}: {error}; '
                              f'{env_path} was left untouched. Next: fix the archive folder permissions and rerun.')
    metadata = env_path.stat()
    write_atomic_bytes(env_path, b''.join(kept), stat.S_IMODE(metadata.st_mode), metadata.st_uid, metadata.st_gid)
    return True


def mixed_tree(source):
    return (Path(source) / 'deploy/compose.telemetry.yml').exists()


def retire(env_path=None, runner=None, purge=False, dry_run=False, source=None, archive_stamp=None):
    """Run every step in order; raise RetireError on the first failure (no partial success banner).

    Everything is read and validated first (the mixed-tree guard, the exact bytes of .env, the
    safety of the two fixed paths) before any destructive action; only then are containers,
    volumes, networks, images, the two fixed directories and .env actually changed, in that order.
    """
    source = Path(source) if source else SOURCE
    env_path = Path(env_path) if env_path else source / 'clab-backup-ui/.env'

    # ---- read and validate everything; nothing destructive yet -------------------------------
    if mixed_tree(source):
        raise RetireError(str(source / 'deploy/compose.telemetry.yml')
                          + ' still exists in this source tree; this is a mixed checkout. Complete the '
                            'retirement merge (a matching source release) before running retire-telemetry.sh.')
    env_exists, env_bytes = read_env_bytes(env_path)
    lines = split_env_lines(env_bytes) if env_exists else []
    values = read_values(env_bytes.decode('utf-8')) if env_exists else {}

    config_dir = fixed_config_dir()
    maps_root = fixed_maps_root()
    note_env_override(values, 'TELEMETRY_CONFIG_DIR', config_dir)
    note_env_override(values, 'TELEMETRY_MAPS_DIR', fixed_maps_leaf())
    config_safe = not config_dir.exists() or path_is_plain(config_dir)
    maps_safe = not maps_root.exists() or path_is_plain(maps_root)

    print(f'Looking for the retired telemetry Compose project ({PROJECT})...')
    containers = discover_containers(runner)
    volumes = discover_volumes(runner)
    networks = discover_networks(runner)
    if not (containers or volumes or networks):
        print('No labelled telemetry containers, volumes or networks found.')

    # ---- destructive steps, in order -----------------------------------------------------------
    remove_containers(runner, containers, dry_run)
    remove_volumes(runner, volumes, dry_run)
    remove_networks(runner, networks, dry_run)
    removed_images = remove_images(runner, containers, dry_run)

    archive = prepare_archive(archive_stamp)
    if config_safe:
        found_config = retire_directory(config_dir, archive / 'config', purge, dry_run)
    else:
        print(f'{config_dir}: resolves elsewhere or contains a symlink; left alone. Inspect it by hand.')
        found_config = False
    if maps_safe:
        # TELEMETRY_MAPS_DIR's parent is exclusively feature-owned too (nothing else lives under
        # data/telemetry), so the whole folder is archived/deleted, not just the leaf dashboards dir.
        found_maps = retire_directory(maps_root, archive / 'dashboards', purge, dry_run)
    else:
        print(f'{maps_root}: resolves elsewhere or contains a symlink; left alone. Inspect it by hand.')
        found_maps = False

    changed_env = update_env(env_path, env_exists, lines, archive, purge, dry_run)
    found_anything = bool(containers or volumes or networks or removed_images or found_config or found_maps or changed_env)
    if not found_anything:
        print('Nothing to retire: no telemetry containers, volumes, networks, images, files or .env keys were found.')
    elif dry_run:
        print('Dry run only: nothing on disk or in .env was changed.')
    else:
        print('Retired telemetry stack removed.')
    return found_anything


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    purge = False
    dry_run = False
    for option in argv:
        if option == '--purge':
            purge = True
        elif option == '--dry-run':
            dry_run = True
        else:
            print('Usage: retire_telemetry.py [--purge] [--dry-run]', file=sys.stderr)
            return 64
    try:
        retire(purge=purge, dry_run=dry_run)
    except RetireError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
