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
    def serve(self, records, code=0):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
        port=listener.getsockname()[1];key=paramiko.RSAKey.generate(1024);server=InspectionServer();server.payload=None
        def run():
            transport=None
            try:
                sock,_=listener.accept();transport=paramiko.Transport(sock);transport.add_server_key(key);transport.start_server(server=server)
                channel=transport.accept(5)
                if channel and server.request.wait(5):
                    data=b''
                    while True:
                        chunk=channel.recv(65536)
                        if not chunk:break
                        data+=chunk
                    server.payload=json.loads(data)
                    for item in records:
                        raw=(json.dumps(item)+'\n').encode()
                        channel.sendall(raw[:7]);channel.sendall(raw[7:])
                    channel.send_exit_status(code);channel.shutdown_write();threading.Event().wait(.1)
            except (EOFError,OSError,paramiko.SSHException):pass
            finally:
                if transport:transport.close()
                listener.close()
        thread=threading.Thread(target=run,daemon=True);thread.start()
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

    def test_key_mismatch_sends_no_command(self):
        host,server,thread=self.serve([]);host['fingerprint']='SHA256:wrong'
        with self.assertRaisesRegex(ValueError,'host key changed'):remote(host,{'mode':'capabilities'})
        thread.join(2);self.assertIsNone(server.command)
