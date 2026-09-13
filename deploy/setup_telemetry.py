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
        'TELEMETRY_GRAFANA_ADMIN_PASSWORD', 'TELEMETRY_CONFIG_DIR')
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
    config_dir = Path(config_dir)
    updates = {'TELEMETRY_STACK': 'grafana' if enable else 'disabled', 'TELEMETRY_GRAFANA_PORT': str(grafana_port),
               'TELEMETRY_GRAFANA_BIND': bind, 'TELEMETRY_PROMETHEUS_PORT': str(prometheus_port),
               'TELEMETRY_GRAFANA_ADMIN_PASSWORD': password, 'TELEMETRY_CONFIG_DIR': str(config_dir)}
    lines = [line for line in old.splitlines() if not any(re.match(r'^\s*' + key + r'\s*=', line) for key in KEYS)]
    lines.extend(key + '=' + value for key, value in updates.items())
    write_atomic(env_path, '\n'.join(lines) + '\n', stat.S_IRUSR | stat.S_IWUSR, metadata.st_uid, metadata.st_gid)
    if enable:
        config_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        # World-readable: Prometheus runs as nobody and only needs to read it.
        write_atomic(config_dir / 'prometheus.yml', PROMETHEUS.format(ui_port=ui_port), 0o644, os.getuid(), os.getgid())
    return {'ui_port': ui_port, 'grafana_port': grafana_port, 'prometheus_port': prometheus_port, 'bind': bind}


if __name__ == '__main__':
    try:
        enable = '--remove' not in sys.argv[3:]
        result = configure(sys.argv[1], sys.argv[2], enable)
    except (OSError, ValueError, IndexError) as error:
        sys.exit(str(error) or 'Usage: setup_telemetry.py ENV_FILE CONFIG_DIR [--remove]')
    if enable:
        print(f"Telemetry dashboard settings saved: Grafana on {result['bind']}:{result['grafana_port']}, Prometheus on 127.0.0.1:{result['prometheus_port']} scraping the manager on port {result['ui_port']}. Unrelated settings and an existing admin password were retained.")
    else:
        print('Telemetry dashboards disabled in .env; the admin password was retained for a later reinstall.')
