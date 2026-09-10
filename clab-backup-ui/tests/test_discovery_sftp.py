"""Direct inspection and read-only SFTP through the same real SSH connection."""
import io
import json
import socket
import stat
import threading
import unittest

import paramiko

from app.discovery import COMMANDS, inspect_host
from app.vm_files import decode_bundle
from test_discovery import YAML, response
from test_discovery_ssh import InspectionServer

ROOT = '/etc/containerlab/training'
DEFINITION = ROOT + '/training.clab.yaml'
INVENTORY = ROOT + '/clab-training/ansible-inventory.yml'


def attrs(mode, size=0):
    value = paramiko.SFTPAttributes()
    value.st_mode = mode; value.st_size = size; value.st_mtime = 100
    return value


class MemoryHandle(paramiko.SFTPHandle):
    def __init__(self, data):
        super().__init__()
        self.readfile = io.BytesIO(data)
        self.size = len(data)

    def stat(self): return attrs(stat.S_IFREG | 0o600, self.size)


class Files(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.server = server

    def lstat(self, path):
        if path in ('/', '/etc', '/etc/containerlab', ROOT, ROOT + '/clab-training'):
            return attrs(stat.S_IFDIR | 0o755)
        if path == DEFINITION and self.server.denied: return paramiko.SFTP_PERMISSION_DENIED
        if path in self.server.files:
            return attrs(stat.S_IFREG | 0o600, len(self.server.files[path]))
        return paramiko.SFTP_NO_SUCH_FILE

    def open(self, path, flags, attr):
        self.server.reads.append(path)
        if flags != 0: return paramiko.SFTP_PERMISSION_DENIED
        if path in self.server.files: return MemoryHandle(self.server.files[path])
        return paramiko.SFTP_NO_SUCH_FILE


class DirectSFTPTests(unittest.TestCase):
    def inspect(self, denied=False, subsystem=True):
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(5)
        port = listener.getsockname()[1]
        server = InspectionServer(); server.reads = []; server.denied = denied
        server.files = {DEFINITION: YAML, INVENTORY: b'all: {hosts: {}}'}
        key = paramiko.RSAKey.generate(1024)
        inspection = json.loads(response())
        for row in inspection['training']: row['absLabPath'] = DEFINITION
        done = threading.Event()
        def run():
            transport = None
            try:
                sock, _ = listener.accept(); transport = paramiko.Transport(sock)
                transport.add_server_key(key)
                if subsystem: transport.set_subsystem_handler('sftp', paramiko.SFTPServer, Files)
                transport.start_server(server=server)
                channel = transport.accept(5)
                if channel and server.request.wait(5):
                    channel.sendall(json.dumps(inspection).encode())
                    channel.send_exit_status(0); channel.shutdown_write()
                    # Keep the next session alive while Paramiko's SFTP handler runs.
                    next_channel = transport.accept(5)
                    done.wait(5)
                    if next_channel: next_channel.close()
            except (EOFError, OSError, paramiko.SSHException): pass
            finally:
                if transport: transport.close()
                listener.close()
        thread = threading.Thread(target=run, daemon=True); thread.start()
        host = dict(address='127.0.0.1', port=port, username='fixture', password='fixture', auth='password', command_mode='direct')
        try: result = inspect_host(host)
        finally: done.set(); thread.join(6)
        self.assertEqual(server.command, COMMANDS['direct'])
        return result[0], server

    def test_original_and_standard_generated_folder_over_same_ssh_connection(self):
        snapshot, server = self.inspect()
        self.assertEqual(snapshot.reader, 'sftp')
        bundle = decode_bundle(snapshot.sources['training'])
        self.assertEqual(bundle['files']['definition'], YAML)
        self.assertEqual(bundle['manifest']['inventory']['path'], INVENTORY)
        self.assertEqual(set(server.reads), {DEFINITION, INVENTORY})

    def test_unreadable_definition_keeps_discovered_nodes_and_reason(self):
        snapshot, server = self.inspect(denied=True)
        self.assertEqual(len(snapshot['training']), 2)
        self.assertEqual(snapshot.sources['training']['reports']['definition']['status'], 'permission_denied')
        self.assertNotIn(DEFINITION, server.reads)

    def test_no_sftp_keeps_inspection_and_reports_fallback(self):
        snapshot, server = self.inspect(subsystem=False)
        self.assertEqual(len(snapshot['training']), 2)
        self.assertEqual(snapshot.sources['training']['reports']['definition']['status'], 'sftp_unavailable')
        self.assertEqual(server.reads, [])
