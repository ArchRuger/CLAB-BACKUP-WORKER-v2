"""Exercise structured requests and streamed NDJSON over real local SSH sockets."""
import base64
import hashlib
import json
import socket
import threading
import unittest
import paramiko
from app.lab_operations import remote
from test_discovery_ssh import InspectionServer


class OperationsSSHTests(unittest.TestCase):
    def serve(self, records, code=0, status_before_tail=None, stderr=b'', raw_tail=b''):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
        port=listener.getsockname()[1];key=paramiko.RSAKey.generate(1024);server=InspectionServer();server.payload=None
        active_transport=[None]
        def run():
            transport=None;watchdog=None
            try:
                sock,_=listener.accept();transport=paramiko.Transport(sock);active_transport[0]=transport
                watchdog=threading.Timer(30, transport.close);watchdog.daemon=True;watchdog.start()
                transport.add_server_key(key);transport.start_server(server=server)
                channel=transport.accept(5)
                if channel:channel.settimeout(5)
                if channel and server.request.wait(5):
                    data=b''
                    while True:
                        chunk=channel.recv(65536)
                        if not chunk:break
                        data+=chunk
                    server.payload=json.loads(data)
                    stderr_offset=0
                    while stderr_offset<len(stderr):
                        sent=channel.send_stderr(stderr[stderr_offset:stderr_offset+65536])
                        if not sent:break
                        stderr_offset+=sent
                    if status_before_tail is None:
                        for item in records:
                            raw=(json.dumps(item)+'\n').encode()
                            channel.sendall(raw[:7]);channel.sendall(raw[7:])
                        if code is not None:
                            channel.send_exit_status(code)
                    else:
                        # Exit status is channel metadata, not an end-of-output
                        # marker. Leave time for the client to observe it before
                        # the final stdout bytes and EOF arrive.
                        raw=b''.join((json.dumps(item)+'\n').encode() for item in records)
                        if status_before_tail:
                            channel.sendall(raw[:status_before_tail])
                        if code is not None:
                            channel.send_exit_status(code)
                        threading.Event().wait(.15)
                        for offset in range(status_before_tail, len(raw), 4096):
                            channel.sendall(raw[offset:offset+4096])
                            threading.Event().wait(.001)
                    if raw_tail:
                        channel.sendall(raw_tail)
                    channel.shutdown_write();threading.Event().wait(.1)
            except (EOFError,OSError,paramiko.SSHException):pass
            finally:
                if watchdog:watchdog.cancel()
                if transport:transport.close()
                listener.close()
                if watchdog:watchdog.join(1)
        thread=threading.Thread(target=run,daemon=True);thread.start()
        def cleanup():
            listener.close()
            if active_transport[0]:active_transport[0].close()
            thread.join(6)
            self.assertFalse(thread.is_alive(), 'Local SSH fixture did not stop after cleanup.')
        self.addCleanup(cleanup)
        fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        host=dict(enabled=True,address='127.0.0.1',port=port,username='fixture',password='fixture',auth='password',fingerprint=fingerprint)
        return host,server,thread

    def test_stdin_is_structured_and_output_is_streamed(self):
        host,server,thread=self.serve([{'heartbeat':True},{'output':'hello\n'},{'result':{'exit_code':0}}])
        output=[];req=dict(mode='run',action='inspect',path='/etc/labs/space name.yaml',options={})
        self.assertEqual(remote(host,req,output.append),{'exit_code':0});thread.join(2)
        self.assertEqual(server.command,'clab-manager-operations');self.assertEqual(server.payload,req);self.assertEqual(output,['hello\n'])

    def test_error_and_failed_exit_never_report_success(self):
        for records,code in (([{'error':'The topology changed; review again.'}],1),([{'result':{'exit_code':0}}],1)):
            host,server,thread=self.serve(records,code)
            with self.assertRaises(ValueError):remote(host,{'mode':'capabilities'})
            thread.join(2)

    def test_exit_status_before_delayed_result_waits_for_stdout_eof(self):
        expected={'path':'/etc/containerlab','entries':[]}
        host,server,thread=self.serve([{'result':expected}], status_before_tail=0)
        try:
            self.assertEqual(remote(host, {'mode':'browse','path':'/etc/containerlab'}), expected)
        finally:
            thread.join(2)

    def test_exit_status_before_large_multipart_result_tail(self):
        expected={'path':'/etc/containerlab/training.clab.yaml','text':'x'*(160*1024)}
        host,server,thread=self.serve([{'result':expected}], status_before_tail=23)
        try:
            self.assertEqual(remote(host, {'mode':'read','path':expected['path']}), expected)
        finally:
            thread.join(2)

    def test_stdout_eof_without_result_never_reports_success(self):
        host,server,thread=self.serve([{'heartbeat':True}])
        try:
            with self.assertRaises(ValueError):
                remote(host, {'mode':'capabilities'})
        finally:
            thread.join(2)

    def test_nonzero_exit_before_delayed_result_never_reports_success(self):
        host,server,thread=self.serve([{'result':{'exit_code':0}}], code=1, status_before_tail=0)
        try:
            with self.assertRaises(ValueError):
                remote(host, {'mode':'capabilities'})
        finally:
            thread.join(2)

    def test_sudo_stderr_has_targeted_repair_without_exposing_diagnostics(self):
        host,server,thread=self.serve([], code=1,
            stderr=b'sudo: a password is required\nfixture-secret-password\n')
        try:
            with self.assertRaisesRegex(ValueError, 'restricted sudo permission') as failure:
                remote(host, {'mode':'capabilities'})
            self.assertNotIn('fixture-secret-password', str(failure.exception))
        finally:
            thread.join(2)

    def test_command_not_found_stderr_identifies_wrong_vm_account(self):
        host,server,thread=self.serve([], code=127,
            stderr=b'sh: 1: clab-manager-operations: not found\nfixture-secret-password\n')
        try:
            with self.assertRaisesRegex(ValueError, 'not using the operations gateway') as failure:
                remote(host, {'mode':'capabilities'})
            self.assertIn('clab-discovery', str(failure.exception))
            self.assertNotIn('fixture-secret-password', str(failure.exception))
        finally:
            thread.join(2)

    def test_eof_without_exit_status_never_reports_success(self):
        host,server,thread=self.serve([{'result':{'exit_code':0}}], code=None)
        try:
            with self.assertRaisesRegex(ValueError, 'exit status'):
                remote(host, {'mode':'capabilities'})
        finally:
            thread.join(2)

    def test_truncated_record_after_valid_result_never_reports_success(self):
        host,server,thread=self.serve([{'result':{'exit_code':0}}], raw_tail=b'{"result":')
        try:
            with self.assertRaises(ValueError):
                remote(host, {'mode':'capabilities'})
        finally:
            thread.join(2)

    def test_oversized_stderr_is_bounded_without_exposing_diagnostics(self):
        host,server,thread=self.serve([{'result':{'exit_code':0}}],
            stderr=b'fixture-secret-password\n'+b'x'*(6*1024*1024))
        try:
            with self.assertRaisesRegex(ValueError, 'exceeded|too large') as failure:
                remote(host, {'mode':'capabilities'})
            self.assertNotIn('fixture-secret-password', str(failure.exception))
        finally:
            thread.join(2)

    def test_large_stderr_is_drained_before_success(self):
        expected={'path':'/etc/containerlab','entries':[]}
        host,server,thread=self.serve([{'result':expected}],
            stderr=b'fixture-secret-password\n'+b'x'*(512*1024))
        try:
            self.assertEqual(remote(host, {'mode':'browse','path':expected['path']}), expected)
        finally:
            thread.join(2)

    def test_unknown_stderr_reports_exit_status_without_exposing_diagnostics(self):
        host,server,thread=self.serve([], code=42, stderr=b'fixture-secret-password\n')
        try:
            with self.assertRaisesRegex(ValueError, '42') as failure:
                remote(host, {'mode':'capabilities'})
            self.assertNotIn('fixture-secret-password', str(failure.exception))
        finally:
            thread.join(2)

    def test_key_mismatch_sends_no_command(self):
        host,server,thread=self.serve([]);host['fingerprint']='SHA256:wrong'
        with self.assertRaisesRegex(ValueError,'host key changed'):remote(host,{'mode':'capabilities'})
        thread.join(2);self.assertIsNone(server.command)
