"""Opt-in integration: real Ansible EOS driver against a simulated SSH CLI."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import paramiko
from app.runner import Runner, filename
from app.store import Store

class SSHServer(paramiko.ServerInterface):
    def __init__(self): self.shell=threading.Event()
    def check_auth_password(self,username,password):
        return paramiko.AUTH_SUCCESSFUL if username=='admin' and password=='login-fixture' else paramiko.AUTH_FAILED
    def get_allowed_auths(self,username): return 'password'
    def check_channel_request(self,kind,chanid): return paramiko.OPEN_SUCCEEDED
    def check_channel_pty_request(self,*args): return True
    def check_channel_shell_request(self,channel): self.shell.set();return True

@unittest.skipUnless(os.environ.get('RUN_SSH_FIXTURES')=='1','Set RUN_SSH_FIXTURES=1 after installing Ansible collections')
class EOSSSHTests(unittest.TestCase):
    def test_enable_password_and_privileged_running_config(self):
        commands=[];errors=[];transports=[]
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(20)
        port=listener.getsockname()[1]
        def serve():
            try:
                sock,_=listener.accept();transport=paramiko.Transport(sock);transports.append(transport)
                transport.add_server_key(paramiko.RSAKey.generate(2048));server=SSHServer();transport.start_server(server=server)
                channel=transport.accept(15);server.shell.wait(15);channel.send(b'SW1>');pending=b'';enabled=False;password=False
                while transport.is_active():
                    data=channel.recv(4096)
                    if not data: break
                    pending+=data
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1);command=line.decode().strip();commands.append(command)
                        channel.send((command+'\r\n').encode())
                        if password:
                            enabled=command=='enable-fixture';password=False;reply=''
                        elif command=='enable':
                            password=True;channel.send(b'Password: ');continue
                        elif command=='show running-config': reply='! EOS fixture\r\nhostname SW1\r\nend' if enabled else '% Error: privileged mode required'
                        elif command=='show version | json': reply=json.dumps(dict(version='4.35.0F',modelName='cEOSLab'))
                        elif command=='show hostname | json': reply=json.dumps(dict(hostname='SW1'))
                        elif command.startswith('bash '): reply='SWI=flash:/EOS.swi'
                        else: reply=''
                        channel.send((reply+'\r\nSW1'+('#' if enabled else '>')).encode())
            except (EOFError,OSError): pass
            except Exception as exc: errors.append(exc)
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store=Store(tmp);runner=Runner(store)
                node=dict(name='SW1',address='127.0.0.1',port=port,platform='arista_ceos',enabled=True,username='admin',password='login-fixture',enable_password='enable-fixture')
                lab=dict(id='lab',name='Lab',nodes=[node],profiles=[],defaults={})
                job=dict(id='sshfixture',status='queued',nodes=[]);store.state['jobs'].append(job)
                try: runner.execute('sshfixture',lab,[node],'backup')
                finally: runner.close()
                self.assertEqual(job['status'],'succeeded',job)
                self.assertEqual(errors,[])
                self.assertIn('enable',commands);self.assertIn('enable-fixture',commands)
                self.assertLess(commands.index('enable'),commands.index('show running-config'))
                self.assertIn('hostname SW1',(Path(tmp)/'backups/lab/latest'/filename(node)).read_text())
                log=(Path(tmp)/'events.jsonl').read_text()
                self.assertNotIn('enable-fixture',log);self.assertNotIn('hostname SW1',log)
        finally:
            for transport in transports: transport.close()
            listener.close();thread.join(2)
