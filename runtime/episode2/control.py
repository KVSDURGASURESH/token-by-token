#!/usr/bin/python3.12
"""Fixed local image operations. No provider API, shell command, or private recipe."""
from __future__ import annotations
import argparse
import base64
import csv
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

ROOT=Path('/opt/episode2')
MODEL=Path('/opt/models/qwen2.5-32b-instruct')
STATE=Path('/run/episode2')
ENGINE_MODULES={'vllm':'vllm.entrypoints.openai.api_server','sglang':'sglang.launch_server'}
MAX_JSON=1024*1024
TOOL_COMPATIBILITY={'profile': 'native performance defaults + tool compatibility', 'tool_choice': 'required', 'vllm': ['--enable-auto-tool-choice', '--tool-call-parser', 'hermes'], 'sglang': ['--tool-call-parser', 'qwen25']}


def require(condition,reason):
    if not condition: raise ValueError(reason)


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(raw): return hashlib.sha256(raw).hexdigest()


def loads_request(raw):
    require(len(raw)<=MAX_JSON,'request_too_large')
    def pairs(items):
        result={}
        for k,v in items:
            require(k not in result,'duplicate_json_key')
            result[k]=v
        return result
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'nonfinite_json'))
    except (UnicodeError,json.JSONDecodeError) as e: raise ValueError('invalid_json') from e


def launch_arguments(engine,common_overrides):
    require(engine in ENGINE_MODULES,'unknown_engine')
    # Performance defaults remain native. This image declares only the fixed
    # tool compatibility profile; arbitrary flags never enter this interface.
    require(isinstance(common_overrides,dict) and not common_overrides,'unbound_common_override')
    return [f'/opt/venvs/{engine}/bin/python','/opt/episode2/runtime/engine_launcher.py',engine,
            '--model' if engine=='vllm' else '--model-path',str(MODEL),
            '--host','127.0.0.1','--port','8000','--served-model-name','episode2-model'] + TOOL_COMPATIBILITY[engine]


def validate_request(obj,execution_sha256):
    require(isinstance(obj,dict),'request_not_object')
    operation=obj.get('operation')
    keys={'operation','execution_sha256','epoch_id','timeout_seconds'}
    extras={'inventory':set(),'status':set(),'stop':set(),'start':{'engine','common_overrides'},
            'tokenize':{'engine','messages','tools'},'export':{'kind','max_bytes'}}
    require(operation in extras and set(obj)==keys|extras[operation],'request_fields')
    require(isinstance(execution_sha256,str) and re.fullmatch('[0-9a-f]{64}',execution_sha256)
            and obj['execution_sha256']==execution_sha256,'execution_binding')
    require(isinstance(obj['epoch_id'],str) and re.fullmatch('epoch-[A-Za-z0-9_-]{1,64}',obj['epoch_id']),'epoch_id')
    require(type(obj['timeout_seconds']) is int and 1<=obj['timeout_seconds']<=600,'timeout_seconds')
    if operation=='start': launch_arguments(obj['engine'],obj['common_overrides'])
    if operation=='tokenize':
        require(obj['engine'] in ENGINE_MODULES,'unknown_engine')
        require(isinstance(obj['messages'],list) and 0<len(obj['messages'])<=256,'messages')
        require(isinstance(obj['tools'],list) and len(obj['tools'])<=16,'tools')
        for message in obj['messages']:
            require(isinstance(message,dict) and set(message)<= {'role','content','tool_calls','tool_call_id','name'}
                    and message.get('role') in {'system','user','assistant','tool'},'message_fields')
    if operation=='export':
        require(obj['kind'] in {'engine_log','payload_manifest','defaults_vllm','defaults_sglang'},'export_kind')
        require(type(obj['max_bytes']) is int and 1<=obj['max_bytes']<=MAX_JSON,'export_bound')
    return obj


def parse_proc_stat(raw):
    pid=int(raw.split(' ',1)[0])
    fields=raw[raw.rfind(')')+2:].split()
    require(len(fields)>=20,'proc_stat')
    return {'pid':pid,'state':fields[0],'ppid':int(fields[1]),'pgid':int(fields[2]),
            'sid':int(fields[3]),'starttime_ticks':int(fields[19])}


def proc_identity(pid):
    return parse_proc_stat(Path(f'/proc/{pid}/stat').read_text())


def run(argv,timeout,*,data=None,limit=2*MAX_JSON):
    import tempfile
    # Child output is file-backed and bounded; caller never supplies executable argv.
    def bounds():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(argv,stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
            stdout=output,stderr=errors,start_new_session=True,preexec_fn=bounds,
            env={**os.environ,'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1',
                 'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
        try: process.communicate(data,timeout=timeout)
        except BaseException as exc:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=5)
            if isinstance(exc,subprocess.TimeoutExpired):
                raise ValueError('command_timeout') from exc
            raise
        require(process.returncode==0,'command_failed')
        require(output.tell()<=limit and errors.tell()<=limit,'command_output_bound')
        output.seek(0)
        return output.read(limit+1)


def gpu_inventory(timeout):
    raw=run(['nvidia-smi','--query-gpu=name,uuid,driver_version,memory.total','--format=csv,noheader,nounits'],timeout)
    rows=list(csv.reader(raw.decode().splitlines()))
    require(len(rows)==1 and len(rows[0])==4,'single_gpu_required')
    name,uuid,driver,memory=[x.strip() for x in rows[0]]
    require('H200' in name,'h200_required')
    return {'name':name,'uuid':uuid,'driver_version':driver,'memory_total_bytes':int(memory)*1024*1024}


def gpu_pids(timeout):
    raw=run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],timeout)
    return sorted({int(x.strip()) for x in raw.decode().splitlines() if x.strip()})


def parse_gpu_usage(raw):
    rows=list(csv.reader(raw.decode().splitlines()))
    require(len(rows)==1 and len(rows[0])==4,'gpu_usage_rows')
    uuid,utilization,used,free=[x.strip() for x in rows[0]]
    require(bool(uuid) and utilization.isdigit() and int(utilization)<=100
            and used.isdigit() and free.isdigit(),'gpu_usage_numbers')
    return {'uuid':uuid,'utilization_percent':float(utilization),
            'memory_used_bytes':int(used)*1024*1024,'memory_free_bytes':int(free)*1024*1024}


def parse_gpu_processes(raw):
    records=[]
    for row in csv.reader(raw.decode().splitlines()):
        require(len(row)==2,'gpu_process_fields')
        pid,memory=[x.strip() for x in row]
        require(pid.isdigit() and int(pid)>0 and memory.isdigit(),'gpu_process_numbers')
        records.append({'pid':int(pid),'gpu_memory_bytes':int(memory)*1024*1024})
    require(len({x['pid'] for x in records})==len(records),'gpu_process_duplicate')
    return sorted(records,key=lambda x:x['pid'])


def cpu_ticks(raw):
    fields=raw.splitlines()[0].split()
    require(fields[0]=='cpu' and len(fields)>=9 and all(x.isdigit() for x in fields[1:9]),'cpu_ticks')
    values=[int(x) for x in fields[1:9]]
    return sum(values),values[3]+values[4]


def host_memory(raw):
    values={}
    for line in raw.splitlines():
        fields=line.split()
        if fields[0] in {'MemTotal:','MemAvailable:'}:
            require(len(fields)==3 and fields[1].isdigit() and fields[2]=='kB'
                    and fields[0] not in values,'host_memory_fields')
            values[fields[0]]=int(fields[1])*1024
    require(set(values)=={'MemTotal:','MemAvailable:'} and 0<=values['MemAvailable:']<=values['MemTotal:']
            and values['MemTotal:']>0,'host_memory_numbers')
    return {'memory_total_bytes':values['MemTotal:'],'memory_available_bytes':values['MemAvailable:']}


def usage_sample(timeout):
    start=time.monotonic_ns();before=cpu_ticks(Path('/proc/stat').read_text())
    time.sleep(.1)
    after=cpu_ticks(Path('/proc/stat').read_text());total=after[0]-before[0];idle=after[1]-before[1]
    require(total>0 and 0<=idle<=total,'cpu_sample_delta')
    host={'cpu_percent':100*(total-idle)/total,'cpu_count':os.cpu_count(),
          **host_memory(Path('/proc/meminfo').read_text())}
    gpu=parse_gpu_usage(run(['nvidia-smi','--query-gpu=uuid,utilization.gpu,memory.used,memory.free',
                            '--format=csv,noheader,nounits'],timeout))
    observed=time.monotonic_ns()
    gpu['processes']=parse_gpu_processes(run(['nvidia-smi','--query-compute-apps=pid,used_gpu_memory',
                                             '--format=csv,noheader,nounits'],timeout))
    return {'window_start_ns':start,'window_end_ns':time.monotonic_ns(),'gpu_observed_ns':observed,'gpu':gpu,'host':host}


def port_open():
    with socket.socket() as s:
        s.settimeout(.25)
        return s.connect_ex(('127.0.0.1',8000))==0


def read_bounded(path,limit):
    require(path.is_file() and not path.is_symlink(),'artifact_not_regular')
    with path.open('rb') as f:
        size=os.fstat(f.fileno()).st_size
        require(size<=limit,'artifact_too_large')
        raw=f.read(limit+1)
        require(len(raw)==size,'artifact_changed')
        return raw


def http_sample(path,timeout):
    require(path in {'/health','/metrics','/server_info'},'http_path')
    connection=http.client.HTTPConnection('127.0.0.1',8000,timeout=min(timeout,10))
    try:
        connection.request('GET',path)
        reply=connection.getresponse(); raw=reply.read(MAX_JSON+1)
        require(len(raw)<=MAX_JSON,'http_output_bound')
        return {'path':path,'http_status':reply.status,'received_monotonic_ns':time.monotonic_ns(),
                'body_base64':base64.b64encode(raw).decode(),'body_sha256':digest(raw)}
    except (OSError,http.client.HTTPException):
        return {'path':path,'http_status':None,'received_monotonic_ns':time.monotonic_ns(),
                'body_base64':None,'body_sha256':None}
    finally: connection.close()


class Controller:
    def __init__(self,root=ROOT,state=STATE):
        self.root=root; self.state=state

    def saved(self):
        p=self.state/'process.json'
        return loads_request(read_bounded(p,16384)) if p.exists() else None

    def owned(self,obj):
        saved=self.saved()
        require(saved is not None and saved['execution_sha256']==obj['execution_sha256']
                and saved['epoch_id']==obj['epoch_id'],'process_owner')
        require(saved['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'boot_identity')
        return saved

    def members(self,saved):
        result=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdigit(): continue
            try: item=proc_identity(int(path.name))
            except (FileNotFoundError,ProcessLookupError): continue
            if item['pgid']!=saved['pid']: continue
            require(item['sid']==saved['pid'] and item['starttime_ticks']>=saved['starttime_ticks'],'process_group_identity')
            if item['pid']==saved['pid']:
                require(item['starttime_ticks']==saved['starttime_ticks'],'process_birth_identity')
            if item['state']!='Z': result.append(item)
        return result

    def start(self,obj):
        old=self.saved()
        require(old is None,'engine_epoch_not_stopped')
        require(not port_open() and not gpu_pids(obj['timeout_seconds']),'preexisting_engine_or_gpu_process')
        gpu_inventory(obj['timeout_seconds'])
        argv=launch_arguments(obj['engine'],obj['common_overrides'])
        log_path=self.state/(obj['epoch_id']+'.log')
        fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as output:
            process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=output,stderr=output,
                start_new_session=True,env={**os.environ,'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1',
                    'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','EPISODE2_EXECUTION_SHA256':obj['execution_sha256'],
                    'EPISODE2_EPOCH_ID':obj['epoch_id'],
                    'PATH':f'/opt/venvs/{obj["engine"]}/bin'+os.pathsep+os.environ.get('PATH',os.defpath)})
        try:
            identity=proc_identity(process.pid)
            saved={'execution_sha256':obj['execution_sha256'],'epoch_id':obj['epoch_id'],'engine':obj['engine'],
                   'pid':process.pid,'starttime_ticks':identity['starttime_ticks'],'argv':argv,
                   'argv_sha256':digest(canonical(argv)),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'started_monotonic_ns':time.monotonic_ns()}
            temp=self.state/'process.json.new'
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f: f.write(canonical(saved)); f.flush(); os.fsync(f.fileno())
            os.replace(temp,self.state/'process.json')
        except BaseException:
            # Popen still owns this unreaped child; its fresh session cannot be
            # mistaken for a recycled PID while ownership persistence fails.
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=5)
            raise
        return {'process':saved,'cache_reset':{'status':'pending_readiness','policy':'fresh_process_epoch'},
                'gpu_effective_defaults':'unverified'}

    def status(self,obj):
        saved=self.owned(obj)
        return {'process':saved,'members':self.members(saved),'gpu':gpu_inventory(obj['timeout_seconds']),
                'gpu_pids':gpu_pids(obj['timeout_seconds']),'usage':usage_sample(obj['timeout_seconds']),'readiness':http_sample('/health',obj['timeout_seconds']),
                'metrics':http_sample('/metrics',obj['timeout_seconds']),
                'server_info':http_sample('/server_info',obj['timeout_seconds']),
                'gpu_effective_defaults':'unverified'}

    def stop(self,obj):
        saved=self.owned(obj); deadline=time.monotonic()+min(obj['timeout_seconds'],60)
        # pidfds protect individual signals from PID reuse; inspect each wave to
        # include descendants created before the engine finishes shutting down.
        for sig in (signal.SIGTERM,signal.SIGKILL):
            while self.members(saved):
                members=self.members(saved)
                for item in members:
                    try:
                        fd=os.pidfd_open(item['pid'])
                        try:
                            current=proc_identity(item['pid'])
                            require(current['starttime_ticks']==item['starttime_ticks'],'pid_reused')
                            signal.pidfd_send_signal(fd,sig)
                        finally: os.close(fd)
                    except (ProcessLookupError,FileNotFoundError): pass
                wait_until=min(deadline,time.monotonic()+(1 if sig==signal.SIGTERM else .2))
                while self.members(saved) and time.monotonic()<wait_until: time.sleep(.05)
                if not self.members(saved) or sig==signal.SIGTERM: break
                require(time.monotonic()<deadline,'stop_timeout')
        require(not self.members(saved),'owned_group_remains')
        require(not port_open() and not gpu_pids(obj['timeout_seconds']),'port_or_gpu_process_remains')
        (self.state/'process.json').unlink()
        return {'stopped':True,'owned_group_empty':True,'port_closed':True,'gpu_pids_empty':True,
                'stopped_monotonic_ns':time.monotonic_ns()}

    def verified_model_artifacts(self,manifest,manifest_sha256,execution_sha256):
        require(isinstance(execution_sha256,str) and re.fullmatch('[0-9a-f]{64}',execution_sha256),'execution_binding')
        items=manifest['model']['artifacts']
        require(isinstance(items,list) and len(items)==24 and len({i['path'] for i in items})==24
                and sum(i['path'].endswith('.safetensors') for i in items)==17,'complete_model_artifacts')
        def identity(p):
            require(p.is_file() and not p.is_symlink(),'model_not_regular')
            s=p.stat()
            return {'dev':s.st_dev,'ino':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
        def snapshot():
            result=[]
            for item in items:
                require(isinstance(item['path'],str) and re.fullmatch('[A-Za-z0-9_.-]+',item['path'])
                        and item['path'] not in {'.','..'},'model_artifact_path')
                require(type(item['size_bytes']) is int and item['size_bytes']>0 and isinstance(item['sha256'],str)
                        and re.fullmatch('[0-9a-f]{64}',item['sha256']),'model_artifact_fields')
                result.append({'path':item['path'],'sha256':item['sha256'],'size_bytes':item['size_bytes'],
                               'identity':identity(MODEL/item['path'])})
            return result
        observed=snapshot()
        expected={'schema_version':'episode2.model-integrity-cache.v1','execution_sha256':execution_sha256,
                  'manifest_sha256':manifest_sha256,'model_root':str(MODEL),'artifacts':observed}
        cache=self.state/'model-integrity-cache.json'
        if cache.exists() or cache.is_symlink():
            require(cache.is_file() and not cache.is_symlink() and cache.stat().st_uid==os.geteuid()
                    and cache.stat().st_mode & 0o777==0o600,'model_cache_private')
            saved=loads_request(read_bounded(cache,MAX_JSON))
            if canonical(saved)==canonical(expected):
                require(snapshot()==observed,'model_artifact_changed')
                return items
        for item,before in zip(items,observed):
            path=MODEL/item['path'];h=hashlib.sha256()
            with path.open('rb') as stream:
                s=os.fstat(stream.fileno())
                opened={'dev':s.st_dev,'ino':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
                require(opened==before['identity'],'model_artifact_changed')
                while chunk:=stream.read(8*1024*1024):h.update(chunk)
                require(identity(path)==before['identity'],'model_artifact_changed')
            require(before['identity']['size']==item['size_bytes'] and h.hexdigest()==item['sha256'],'model_artifact_mismatch')
        require(snapshot()==observed,'model_artifact_changed')
        import tempfile
        require(self.state.is_dir() and not self.state.is_symlink() and self.state.stat().st_uid==os.geteuid(),
                'state_ownership')
        fd,temp=tempfile.mkstemp(prefix='model-integrity-',dir=self.state)
        try:
            with os.fdopen(fd,'wb') as output:output.write(canonical(expected));output.flush();os.fsync(output.fileno())
            os.replace(temp,cache)
        finally:
            if Path(temp).exists():Path(temp).unlink()
        return items

    def inventory(self,obj):
        raw_manifest=read_bounded(self.root/'payload-manifest.json',MAX_JSON)
        manifest=loads_request(raw_manifest);manifest_sha256=digest(raw_manifest)
        verified=self.verified_model_artifacts(manifest,manifest_sha256,obj['execution_sha256'])
        require(digest(read_bounded(self.root/'payload-manifest.json',MAX_JSON))==manifest_sha256,'payload_manifest_changed')
        engines={}
        for engine in ENGINE_MODULES:
            evidence=loads_request(read_bounded(self.root/'build-evidence'/f'{engine}-defaults.json',MAX_JSON))
            engines[engine]=evidence
        return {'gpu':gpu_inventory(obj['timeout_seconds']),'model':{'root':str(MODEL),'artifacts':verified,
                'revision':manifest['model']['revision']},'engines':engines,
                'payload_sha256':manifest_sha256,'disk_free_bytes':os.statvfs(MODEL).f_bavail*os.statvfs(MODEL).f_frsize,
                'gpu_effective_defaults':'unverified'}

    def tokenize(self,obj):
        code='''import json,sys,hashlib
from transformers import AutoTokenizer
obj=json.load(sys.stdin)
t=AutoTokenizer.from_pretrained('/opt/models/qwen2.5-32b-instruct',local_files_only=True,trust_remote_code=False)
tools=obj['tools']
if tools:
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        if obj['engine']=='sglang':
            from sglang.srt.entrypoints.openai.protocol import Tool
        else:
            from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionToolsParam as Tool
        tools=[Tool.model_validate(tool).model_dump() for tool in tools]
kw={'tools':tools} if tools else {}
rendered=t.apply_chat_template(obj['messages'],tokenize=False,add_generation_prompt=True,**kw)
ids=t.apply_chat_template(obj['messages'],tokenize=True,return_dict=False,add_generation_prompt=True,**kw)
assert isinstance(ids,list) and all(type(x) is int for x in ids)
print(json.dumps({'token_count':len(ids),'rendered_sha256':hashlib.sha256(rendered.encode()).hexdigest(),'template_sha256':hashlib.sha256(t.chat_template.encode()).hexdigest()}))
'''
        raw=run([f'/opt/venvs/{obj["engine"]}/bin/python','-c',code],obj['timeout_seconds'],
                data=canonical({'engine':obj['engine'],'messages':obj['messages'],'tools':obj['tools']}))
        return loads_request(raw)

    def export(self,obj):
        paths={'payload_manifest':self.root/'payload-manifest.json',
               'defaults_vllm':self.root/'build-evidence/vllm-defaults.json',
               'defaults_sglang':self.root/'build-evidence/sglang-defaults.json'}
        if obj['kind']=='engine_log':
            self.owned(obj); p=self.state/(obj['epoch_id']+'.log')
            require(p.is_file() and not p.is_symlink(),'log_not_regular')
            with p.open('rb') as f:
                size=os.fstat(f.fileno()).st_size; f.seek(max(0,size-obj['max_bytes'])); raw=f.read(obj['max_bytes'])
            truncated=size>len(raw)
        else:
            raw=read_bounded(paths[obj['kind']],obj['max_bytes']); truncated=False
        return {'kind':obj['kind'],'data_base64':base64.b64encode(raw).decode(),'sha256':digest(raw),
                'size_bytes':len(raw),'truncated':truncated}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        bound=read_bounded(STATE/'execution-sha256',65).decode().strip()
        obj=validate_request(loads_request(sys.stdin.buffer.read(MAX_JSON+1)),bound)
        signal.signal(signal.SIGALRM,lambda *_:require(False,'operation_timeout'))
        signal.alarm(obj['timeout_seconds'])
        require(STATE.is_dir() and not STATE.is_symlink() and STATE.stat().st_uid==0,'state_ownership')
        fd=os.open(STATE/'control.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result=getattr(Controller(),obj['operation'])(obj)
        print(json.dumps({'schema_version':'episode2.control-response.v1','status':'ok',
              'operation':obj['operation'],'execution_sha256':obj['execution_sha256'],'epoch_id':obj['epoch_id'],
              'result':result},separators=(',',':')))
        return 0
    except Exception as exc:
        # Raw tracebacks/URLs/tokens never cross the control protocol.
        code=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[a-z_]{1,80}',str(exc)) else 'control_failed'
        print(json.dumps({'schema_version':'episode2.control-response.v1','status':'error','code':code}))
        return 1


if __name__=='__main__': raise SystemExit(main())
