"""Preserve unrelated dotenv settings while enabling the optional Grafana stack.

Never evaluate dotenv as shell code. Writes the Prometheus scrape configuration for
the manager's actual UI port and keeps an existing Grafana admin password.
"""
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

KEYS = ('TELEMETRY_STACK', 'TELEMETRY_GRAFANA_PORT', 'TELEMETRY_GRAFANA_BIND', 'TELEMETRY_PROMETHEUS_PORT',
        'TELEMETRY_GRAFANA_ADMIN_PASSWORD', 'TELEMETRY_CONFIG_DIR', 'TELEMETRY_MAPS_DIR', 'TELEMETRY_GRAFANA_IDLE_MINUTES')
# The manager (uid 10001 in its container, /data) writes one generated lab-map dashboard per lab here;
# Grafana reads the folder through a read-only bind mount. Keep in step with clab-backup-ui/compose.yml.
DEFAULT_MAPS_DIR = '/srv/containerlab-node-manager/data/telemetry/dashboards'
MANAGER_UID = 10001
GRAFANA_UID = 472
# Grafana is on demand: the manager starts the container by this name (compose.telemetry.yml
# container_name, clab-backup-ui/app/host_operations.py) when someone opens it and stops it after this
# many minutes without a dashboard request; 0 keeps it running once started.
GRAFANA_CONTAINER = 'clab-manager-grafana'
DEFAULT_IDLE_MINUTES = 15
# The Flow panel that draws the lab maps (srl-telemetry-lab uses the same plugin); Apache-2.0,
# community-signed, pinned and installed once into TELEMETRY_CONFIG_DIR/plugins so restarts work offline.
PLUGIN = 'andrewbmchugh-flow-panel'
PLUGIN_VERSION = '1.20.1'
PROMETHEUS = '''# Written by deploy/setup-telemetry.sh for the manager on port {ui_port}. Rerun the setup after changing UI_PORT.
global:
  scrape_interval: 10s
  scrape_timeout: 8s
  evaluation_interval: 30s
scrape_configs:
  - job_name: containerlab-node-manager
    metrics_path: /api/telemetry/metrics
    static_configs:
      - targets: ['127.0.0.1:{ui_port}']
'''


def read_values(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r'^\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$', line)
        if match:
            values[match[1]] = match[2].strip().strip('"\'')
    return values


def port_value(values, key, default):
    raw = values.get(key, '') or str(default)
    if not re.fullmatch(r'\d{1,5}', raw) or not 1 <= int(raw) <= 65535:
        raise ValueError(f'{key} in .env is not a valid TCP port; correct it before running the telemetry setup.')
    return int(raw)


def write_atomic(path, content, mode, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix='.telemetry-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if hasattr(os, 'chown'):
            os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(env_path, config_dir, enable=True):
    env_path = Path(env_path)
    if env_path.is_symlink():
        raise ValueError('Refusing a symlinked .env. Configure telemetry settings manually; see docs/TELEMETRY.md.')
    old = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    metadata = env_path.stat() if env_path.exists() else env_path.parent.stat()
    values = read_values(old)
    ui_port = port_value(values, 'UI_PORT', 8081)
    grafana_port = port_value(values, 'TELEMETRY_GRAFANA_PORT', 3000)
    prometheus_port = port_value(values, 'TELEMETRY_PROMETHEUS_PORT', 9090)
    if len({ui_port, grafana_port, prometheus_port}) != 3:
        raise ValueError('UI_PORT, TELEMETRY_GRAFANA_PORT and TELEMETRY_PROMETHEUS_PORT must differ; they share the host network.')
    bind = values.get('TELEMETRY_GRAFANA_BIND') or '0.0.0.0'
    if not re.fullmatch(r'[0-9A-Za-z.:]{1,64}', bind):
        raise ValueError('TELEMETRY_GRAFANA_BIND in .env must be an IP address.')
    password = values.get('TELEMETRY_GRAFANA_ADMIN_PASSWORD') or secrets.token_urlsafe(18)
    if not re.fullmatch(r'[A-Za-z0-9_.~-]{12,128}', password):
        raise ValueError('Existing TELEMETRY_GRAFANA_ADMIN_PASSWORD contains unsupported characters; it was not replaced.')
    maps_dir = values.get('TELEMETRY_MAPS_DIR') or DEFAULT_MAPS_DIR
    absolute = maps_dir.startswith('/') or bool(re.match(r'^[A-Za-z]:[/\\]', maps_dir))     # the drive form only for tests
    if not absolute or '..' in re.split(r'[/\\]', maps_dir) or not re.fullmatch(r'[A-Za-z0-9_./:\\ -]{1,220}', maps_dir):
        raise ValueError('TELEMETRY_MAPS_DIR in .env must be an absolute path inside the manager data directory.')
    idle = values.get('TELEMETRY_GRAFANA_IDLE_MINUTES') or str(DEFAULT_IDLE_MINUTES)
    if not re.fullmatch(r'\d{1,4}', idle) or int(idle) > 1440:
        raise ValueError('TELEMETRY_GRAFANA_IDLE_MINUTES in .env must be a whole number of minutes (0 to 1440; 0 never stops Grafana automatically).')
    idle = str(int(idle))
    config_dir = Path(config_dir)
    updates = {'TELEMETRY_STACK': 'grafana' if enable else 'disabled', 'TELEMETRY_GRAFANA_PORT': str(grafana_port),
               'TELEMETRY_GRAFANA_BIND': bind, 'TELEMETRY_PROMETHEUS_PORT': str(prometheus_port),
               'TELEMETRY_GRAFANA_ADMIN_PASSWORD': password, 'TELEMETRY_CONFIG_DIR': str(config_dir), 'TELEMETRY_MAPS_DIR': maps_dir,
               'TELEMETRY_GRAFANA_IDLE_MINUTES': idle}
    lines = [line for line in old.splitlines() if not any(re.match(r'^\s*' + key + r'\s*=', line) for key in KEYS)]
    lines.extend(key + '=' + value for key, value in updates.items())
    if enable:
        # Folders first: a missing manager data directory must fail before .env changes.
        config_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        prepare_folders(config_dir, Path(maps_dir))
    write_atomic(env_path, '\n'.join(lines) + '\n', stat.S_IRUSR | stat.S_IWUSR, metadata.st_uid, metadata.st_gid)
    if enable:
        # World-readable: Prometheus runs as nobody and only needs to read it.
        write_atomic(config_dir / 'prometheus.yml', PROMETHEUS.format(ui_port=ui_port), 0o644,
                     getattr(os, 'getuid', lambda: 0)(), getattr(os, 'getgid', lambda: 0)())
    return {'ui_port': ui_port, 'grafana_port': grafana_port, 'prometheus_port': prometheus_port, 'bind': bind, 'maps_dir': maps_dir,
            'idle_minutes': int(idle)}


def is_root():
    return getattr(os, 'geteuid', lambda: 1)() == 0


def owned_dir(path, uid):
    """Create a folder the given service account can use; existing folders are left as they are.
    Without root (tests, CI) the folder simply belongs to the caller."""
    if path.is_dir():
        return
    path.mkdir(mode=0o755)
    if is_root():
        os.chown(path, uid, uid)


def prepare_folders(config_dir, maps_dir):
    """The plugin folder (Grafana's user) and the lab-map folder (the manager's user); Compose refuses
    to create bind sources itself, so both must exist before the stack starts."""
    owned_dir(Path(config_dir) / 'plugins', GRAFANA_UID)
    data_dir = maps_dir.parent.parent
    if not data_dir.is_dir():
        raise ValueError(f'The manager data directory {data_dir} does not exist yet. Run deploy/start-manager.sh (or install.sh) first.')
    owned_dir(maps_dir.parent, MANAGER_UID)
    owned_dir(maps_dir, MANAGER_UID)


def grafana_image(compose_path):
    match = re.search(r'image:\s*(grafana/grafana-oss@sha256:[0-9a-f]{64})', Path(compose_path).read_text(encoding='utf-8'))
    if not match:
        raise ValueError('compose.telemetry.yml does not pin the Grafana image by digest.')
    return match[1]


def plugin_installed(plugins_dir):
    try:
        import json
        meta = json.loads((Path(plugins_dir) / PLUGIN / 'plugin.json').read_text(encoding='utf-8'))
        return meta.get('id') == PLUGIN and meta.get('info', {}).get('version') == PLUGIN_VERSION
    except (OSError, ValueError, AttributeError):
        return False


def install_plugin(config_dir, compose_path=None, runner=None):
    """Install the pinned Flow panel into config_dir/plugins with the pinned Grafana image's own CLI.

    Runs once (idempotent on the recorded version); needs grafana.com during setup only. The plugin is
    community-signed, and Grafana verifies that signature when it loads the folder.
    """
    import subprocess
    plugins = Path(config_dir) / 'plugins'
    if plugin_installed(plugins):
        return 'present'
    image = grafana_image(compose_path or Path(__file__).with_name('compose.telemetry.yml'))
    # As root (the setup script) the files belong to Grafana's user; otherwise (CI smoke) to the caller,
    # which is fine because Grafana only reads the folder.
    user = f'{GRAFANA_UID}:{GRAFANA_UID}' if is_root() else f'{getattr(os, "getuid", lambda: 0)()}:{getattr(os, "getgid", lambda: 0)()}'
    command = ['docker', 'run', '--rm', '--user', user, '--entrypoint', 'grafana',
               '-v', f'{plugins}:/plugins', image, 'cli', '--pluginsDir', '/plugins', 'plugins', 'install', PLUGIN, PLUGIN_VERSION]
    result = (runner or subprocess.run)(command, capture_output=True, text=True)
    if result.returncode != 0 or not plugin_installed(plugins):
        detail = re.sub(r'\s+', ' ', (result.stderr or result.stdout or '').strip())[-300:]
        raise ValueError(f'Installing the Grafana Flow panel ({PLUGIN} {PLUGIN_VERSION}) failed; the VM needs access to '
                         f'grafana.com during this setup. {detail}'.rstrip())
    return 'installed'


def wait_ready(env_path, timeout=90, base='http://127.0.0.1'):
    """Block until Prometheus answers /-/ready and Grafana /api/health, else raise with the reason.

    A stack that starts but crash-loops (a rejected command-line flag, an unreadable
    scrape configuration, a port already in use) must fail the setup loudly instead of
    leaving dashboards that show only errors.
    """
    import json
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import ProxyHandler, build_opener
    values = read_values(Path(env_path).read_text(encoding='utf-8'))
    grafana_port = port_value(values, 'TELEMETRY_GRAFANA_PORT', 3000)
    prometheus_port = port_value(values, 'TELEMETRY_PROMETHEUS_PORT', 9090)
    opener = build_opener(ProxyHandler({}))
    checks = {'Prometheus': (f'{base}:{prometheus_port}/-/ready', None),
              'Grafana': (f'{base}:{grafana_port}/api/health', 'database')}
    deadline = time.monotonic() + timeout
    pending = dict(checks)
    last = {}
    while pending and time.monotonic() < deadline:
        for name, (url, key) in list(pending.items()):
            try:
                with opener.open(url, timeout=5) as response:
                    body = response.read(65536)
                    if key is None or json.loads(body.decode('utf-8', 'replace')).get(key) == 'ok':
                        pending.pop(name)
                        continue
                    last[name] = 'unexpected answer'
            except HTTPError as error:
                last[name] = f'HTTP {error.code}'
            except (URLError, OSError, ValueError) as error:
                last[name] = 'no answer'
        if pending:
            time.sleep(2)
    if pending:
        raise ValueError('Not ready after ' + str(timeout) + ' s: '
                         + ', '.join(f'{name} on 127.0.0.1:{prometheus_port if name == "Prometheus" else grafana_port} ({last.get(name, "no answer")})' for name in pending)
                         + '. The services are not healthy; inspect their logs before using the dashboards.')
    target = f'{base}:{prometheus_port}/api/v1/targets'
    active = []
    # The scrape manager registers its targets a moment after /-/ready; give it a few seconds
    # so the setup can report the manager target instead of an empty list.
    for _ in range(5):
        try:
            with opener.open(target, timeout=5) as response:
                active = json.loads(response.read(1 << 20).decode('utf-8', 'replace')).get('data', {}).get('activeTargets', [])
        except (HTTPError, URLError, OSError, ValueError):
            active = []
        if active:
            break
        time.sleep(2)
    # Anonymous viewers may read the frontend settings; the installed panel plugins are listed there.
    flow_panel = False
    try:
        with opener.open(f'{base}:{grafana_port}/api/frontend/settings', timeout=5) as response:
            panels = json.loads(response.read(4 << 20).decode('utf-8', 'replace')).get('panels', {})
            flow_panel = isinstance(panels, dict) and PLUGIN in panels
    except (HTTPError, URLError, OSError, ValueError):
        flow_panel = False
    return {'grafana_port': grafana_port, 'prometheus_port': prometheus_port, 'flow_panel': flow_panel,
            'targets': [(t.get('scrapeUrl', ''), t.get('health', ''), t.get('lastError', '')) for t in active if isinstance(t, dict)]}


if __name__ == '__main__':
    try:
        if '--wait' in sys.argv[2:]:
            result = wait_ready(sys.argv[1])
            targets = result['targets']
            print(f"Prometheus on 127.0.0.1:{result['prometheus_port']} and Grafana on TCP {result['grafana_port']} are ready.")
            for url, health, error in targets:
                print(f'Scrape target {url}: {health}' + (f' ({error})' if error else '')
                      + ('' if health == 'up' else ' (first scrape pending).' if health == 'unknown'
                         else '. Prometheus retries every 10 s; the target is up once the manager runs with the current .env '
                              '(start-manager.sh creates it, recreate-manager.sh reloads it). Confirm with deploy/check-install.sh.'))
            print(f'Flow panel {PLUGIN} {PLUGIN_VERSION}: ' + ('loaded; the manager-generated lab maps will render.' if result['flow_panel']
                  else 'NOT loaded; lab maps stay empty. Rerun sudo bash deploy/setup-telemetry.sh with access to grafana.com and check the grafana service logs.'))
            sys.exit(0)
        if '--plugin' in sys.argv[3:]:
            state = install_plugin(sys.argv[2])
            print(f'Flow panel {PLUGIN} {PLUGIN_VERSION} {state} in {Path(sys.argv[2]) / "plugins"}.')
            sys.exit(0)
        enable = '--remove' not in sys.argv[3:]
        result = configure(sys.argv[1], sys.argv[2], enable)
    except (OSError, ValueError, IndexError) as error:
        sys.exit(str(error) or 'Usage: setup_telemetry.py ENV_FILE CONFIG_DIR [--remove | --plugin] | setup_telemetry.py ENV_FILE --wait')
    if enable:
        print(f"Telemetry dashboard settings saved: Grafana on {result['bind']}:{result['grafana_port']} (started on request, stopped after "
              f"{result['idle_minutes']} idle minutes), Prometheus on 127.0.0.1:{result['prometheus_port']} scraping the manager on port {result['ui_port']}; "
              f"lab maps are provisioned from {result['maps_dir']}. Unrelated settings and an existing admin password were retained.")
    else:
        print('Telemetry dashboards disabled in .env; the admin password was retained for a later reinstall.')
