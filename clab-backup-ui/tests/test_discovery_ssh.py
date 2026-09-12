"""End-to-end Paramiko transport against a disposable local SSH server."""
import json
import socket
import threading
import unittest
import paramiko

from app.discovery import COMMANDS, inspect_host


class InspectionServer(paramiko.ServerInterface):
    def __init__(self):
        self.command = None
        self.request = threading.Event()

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username,password)==('fixture','fixture') else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username): return 'password'

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command=command.decode();self.request.set();return True


FIXTURE=b'{"lab":[{"lab_name":"lab","name":"clab-lab-r1","kind":"cisco_xrv9k","state":"running","ipv4_address":"172.20.20.2/24"}]}'


class SSHDiscoveryTests(unittest.TestCase):
    def serve(self, status=0, data=None, status_before_tail=None):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
        server=InspectionServer();key=paramiko.RSAKey.generate(1024)
        def run():
            transport=None
            try:
                sock,_=listener.accept();transport=paramiko.Transport(sock)
                transport.add_server_key(key);transport.start_server(server=server)
                channel=transport.accept(5)
                if channel and server.request.wait(5):
                    channel.send_stderr(b'fixture diagnostic\n')
                    raw=data or FIXTURE
                    if status_before_tail is None:
                        channel.sendall(raw);channel.send_exit_status(status)
                    else:
                        # OpenSSH may report the helper's exit status while its
                        # final stdout bytes are still queued in the pipe.
                        channel.sendall(raw[:status_before_tail]);channel.send_exit_status(status)
                        threading.Event().wait(.15)
                        for offset in range(status_before_tail,len(raw),4096):
                            channel.sendall(raw[offset:offset+4096]);threading.Event().wait(.001)
                    channel.shutdown_write()
                    server.request.clear();server.request.wait(.1)
            except (EOFError, OSError, paramiko.SSHException):pass
            finally:
                if transport:transport.close()
                listener.close()
        thread=threading.Thread(target=run,daemon=True);thread.start()
        host=dict(address='127.0.0.1',port=listener.getsockname()[1],username='fixture',password='fixture',auth='password',command_mode='helper')
        return host,server,thread

    def test_fixed_command_json_and_fingerprint_over_real_ssh(self):
        host,server,thread=self.serve()
        labs,fingerprint=inspect_host(host)
        thread.join(2)
        self.assertEqual(server.command,COMMANDS['helper'])
        self.assertEqual(labs['lab'][0]['address'],'172.20.20.2')
        self.assertTrue(fingerprint.startswith('SHA256:'))

    def test_exit_status_before_delayed_tail_waits_for_stdout_eof(self):
        host,server,thread=self.serve(status_before_tail=0)
        labs,_=inspect_host(host)
        thread.join(2)
        self.assertEqual(labs['lab'][0]['address'],'172.20.20.2')

    def test_exit_status_before_large_multipart_tail(self):
        rows=[{"lab_name":"lab","name":"clab-lab-r%d"%i,"kind":"cisco_xrv9k","state":"running","ipv4_address":"172.20.20.%d/24"%(i%250+2)} for i in range(1500)]
        raw=json.dumps({"lab":rows}).encode()
        self.assertGreater(len(raw),160*1024)
        host,server,thread=self.serve(data=raw,status_before_tail=23)
        labs,_=inspect_host(host)
        thread.join(2)
        self.assertEqual(len(labs['lab']),1500)

    def test_nonzero_exit_before_delayed_tail_never_accepts_json(self):
        host,server,thread=self.serve(status=1,status_before_tail=0)
        with self.assertRaisesRegex(ValueError,'Inspection command failed'):inspect_host(host)
        thread.join(2)

    def test_nonzero_exit_does_not_accept_plausible_json(self):
        host,server,thread=self.serve(status=1)
        with self.assertRaisesRegex(ValueError,'Inspection command failed'):inspect_host(host)
        thread.join(2)

    def test_host_key_mismatch_prevents_remote_command(self):
        host,server,thread=self.serve();host['fingerprint']='SHA256:wrong'
        with self.assertRaisesRegex(ValueError,'host key changed'):inspect_host(host)
        thread.join(2)
        self.assertIsNone(server.command)
