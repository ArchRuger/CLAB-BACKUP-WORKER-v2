"""Private IPC events. stdout stays private and is never an operational log."""
import json
import os
from datetime import datetime, timezone
from ansible.plugins.callback import CallbackBase

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'backup_events'

    def write(self, event):
        with open(os.environ['BACKUP_EVENT_FILE'],'a',encoding='utf8') as stream:
            stream.write(json.dumps(event)+'\n')

    def v2_runner_on_start(self, host, task):
        self.write({'host':host.get_name(), 'status':'running', 'task':task.get_name()})

    def emit(self, result, status):
        data = result._result
        event = {'host':result._host.get_name(), 'status':status,
                 'task':result._task.get_name(),
                 'captured_at':datetime.now(timezone.utc).isoformat()}
        if status == 'ok':
            output=data.get('stdout','')
            event['stdout'] = '\n'.join(output) if isinstance(output,list) else output
        else:
            event['message'] = str(data.get('msg','SSH command failed'))
        self.write(event)
    def v2_runner_on_ok(self, result):
        self.emit(result,'ok')
    def v2_runner_on_failed(self, result, ignore_errors=False):
        self.emit(result,'failed')
    def v2_runner_on_unreachable(self, result):
        self.emit(result,'unreachable')
