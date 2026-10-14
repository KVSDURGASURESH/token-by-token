#!/usr/bin/env python3
"""Fixed hash-locked direct SSH setup; caller owns allocation and termination."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, os, platform, re, shutil, signal, subprocess, sys, tarfile, time
from pathlib import Path

MODEL=Path('/opt/models/qwen2.5-32b-instruct')
REVISION='5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd'
VERSIONS={'vllm':'0.29.0','sglang':'0.5.20'}

BOOTSTRAP_STAGE='entry'
SAFE_STAGES={'entry','bootstrap_assets','host_prerequisites','source_integrity','execution_authority','model_manifest','filesystem','disk','shared_memory','driver','uv','vllm_install','sglang_install','vllm_dependency_validation','sglang_dependency_validation','vllm_gpu_self_test','sglang_gpu_self_test','model_download','model_integrity','control_install','receipt'}
SAFE_CODES={'setup_disk_capacity', 'artifact_size', 'artifact_hash', 'model_path', 'existing_execution_binding', 'system_python312_and_compiler_required', 'bootstrap_child_failed', 'fresh_engine_environments_required', 'complete_model_required', 'setup_deadline', 'source_path', 'uv_version', 'single_h200_required', 'model_binding', 'root_bootstrap_required', 'model_artifacts', 'uv_archive_member', 'state_owner_permissions', 'duplicate_model_artifact', 'state_symlink', 'dependency_closure_failed', 'execution_environment_mismatch', 'execution_sha256', 'linux_amd64_python312_required', 'glibc_required', 'cuda13_driver_required', 'existing_control_process', 'shared_memory_required', 'model_artifact'}

class BootstrapError(ValueError):
    def __init__(self,code):
        self.code=code if code in SAFE_CODES else 'bootstrap_unexpected_error'
        super().__init__(self.code)

def set_stage(stage):
    global BOOTSTRAP_STAGE
    BOOTSTRAP_STAGE=stage if stage in SAFE_STAGES else 'entry'

def safe_failure(exc,stage):
    code=exc.code if isinstance(exc,BootstrapError) else 'bootstrap_unexpected_error'
    if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)):code='setup_deadline_exceeded'
    elif isinstance(exc,FileNotFoundError):code='required_file_missing'
    elif isinstance(exc,PermissionError):code='required_permission_missing'
    return {'schema_version':'episode2.direct-ssh-bootstrap-result.v1','status':'fail','error_type':type(exc).__name__ if type(exc) in (BootstrapError,ValueError,TimeoutError,FileNotFoundError,PermissionError,subprocess.TimeoutExpired) else 'UnexpectedError','error_code':code,'stage':stage if stage in SAFE_STAGES else 'entry','on_failure':'terminate','service_ready':False}

def require(ok,reason):
    if not ok: raise BootstrapError(reason)

class Deadline:
    def __init__(self,seconds,clock=time.monotonic):
        require(type(seconds) is int and 1<=seconds<=1800,'setup_deadline')
        self.clock=clock;self.start=clock();self.end=self.start+seconds
    def remaining(self):
        left=self.end-self.clock()
        if left<=0: raise TimeoutError('setup_deadline_exceeded')
        return left

def verify_file(path,item,deadline=None):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size==item['size_bytes'],'artifact_size')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):
            if deadline is not None:deadline.remaining()
            digest.update(block)
    require(digest.hexdigest()==item['sha256'],'artifact_hash')

def validate_model(model):
    require(set(model)=={'repository','revision','artifacts'} and model['repository']=='Qwen/Qwen2.5-32B-Instruct' and model['revision']==REVISION,'model_binding')
    require(isinstance(model['artifacts'],list) and model['artifacts'],'model_artifacts')
    names=[]
    for item in model['artifacts']:
        require(set(item)=={'path','sha256','size_bytes'} and isinstance(item['path'],str) and re.fullmatch(r'[A-Za-z0-9_.-]+',item['path']) and item['path'] not in {'.','..'},'model_path')
        require(isinstance(item['sha256'],str) and re.fullmatch('[0-9a-f]{64}',item['sha256']) and type(item['size_bytes']) is int and item['size_bytes']>0,'model_artifact')
        names.append(item['path'])
    require(len(names)==len(set(names)),'duplicate_model_artifact')

def initialize_authority(execution_sha256,state=Path('/run/episode2')):
    require(isinstance(execution_sha256,str) and re.fullmatch('[0-9a-f]{64}',execution_sha256),'execution_sha256')
    inherited=os.environ.get('EPISODE2_EXECUTION_SHA256')
    require(inherited is None or inherited==execution_sha256,'execution_environment_mismatch')
    require(not state.is_symlink(),'state_symlink')
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    require(state.stat().st_uid==os.geteuid() and state.stat().st_mode & 0o777==0o700,'state_owner_permissions')
    require(not (state/'process.json').exists(),'existing_control_process')
    marker=state/'execution-sha256'
    if marker.exists():
        require(not marker.is_symlink() and marker.stat().st_uid==os.geteuid() and marker.read_text()==execution_sha256+'\n','existing_execution_binding')
    else:
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(execution_sha256+'\n')

def install_commands(root,python):
    commands=[]
    for engine in VERSIONS:
        commands += [[str(root/'tools/uv'),'venv','--python',str(python),'--no-python-downloads',f'/opt/venvs/{engine}'],
                     [str(root/'tools/uv'),'pip','sync','--python',f'/opt/venvs/{engine}/bin/python','--require-hashes','--index-strategy','unsafe-best-match','--only-binary',':all:',str(root/f'locks/{engine}.lock')]]
    return commands

def run(argv,deadline,log,*,capture=False):
    env={**os.environ,'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':'/opt/episode2/src','UV_PYTHON_DOWNLOADS':'never','UV_CACHE_DIR':'/opt/episode2/uv-cache','HF_HUB_DOWNLOAD_TIMEOUT':'30','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1'}
    for key in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_TOKEN','HUGGING_FACE_HUB_TOKEN'):env.pop(key,None)
    process=subprocess.Popen(argv,stdout=subprocess.PIPE if capture else log,stderr=log,start_new_session=True,env=env)
    try:out,_=process.communicate(timeout=deadline.remaining())
    except BaseException:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=5);raise
    require(process.returncode==0,'bootstrap_child_failed')
    return out

GPU_PROBE="""import importlib,importlib.metadata as md,json,sys,torch
engine=sys.argv[1];expected=sys.argv[2]
assert md.version(engine)==expected
assert torch.cuda.is_available() and torch.version.cuda=='13.0'
assert torch.cuda.device_count()==1 and 'H200' in torch.cuda.get_device_name(0)
assert torch.cuda.get_device_capability(0)==(9,0)
importlib.import_module('vllm._custom_ops' if engine=='vllm' else 'sgl_kernel')
a=torch.ones((32,32),device='cuda');b=a@a;torch.cuda.synchronize();assert b[0,0].item()==32
print(json.dumps({'engine':engine,'version':md.version(engine),'torch':torch.__version__,'cuda':torch.version.cuda,'device':torch.cuda.get_device_name(0),'compute_capability':[9,0],'actual_cuda_matmul':True,'serving_verified':False}))
"""
DOWNLOAD="""import concurrent.futures,json,sys
from pathlib import Path
from huggingface_hub import hf_hub_download
m=json.loads(Path(sys.argv[1]).read_text())['model'];dest=sys.argv[2]
def fetch(i):
 return hf_hub_download(repo_id=m['repository'],filename=i['path'],revision=m['revision'],local_dir=dest,token=False)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(fetch,m['artifacts']))
"""

def bootstrap(root,seconds,execution_sha256):
    set_stage('bootstrap_assets')
    deadline=Deadline(seconds);assets=json.loads((root/'bootstrap-assets.json').read_text());model=assets['model'];validate_model(model)
    set_stage('host_prerequisites')
    require(os.geteuid()==0,'root_bootstrap_required')
    require(platform.system()=='Linux' and platform.machine()=='x86_64' and sys.version_info[:2]==(3,12),'linux_amd64_python312_required')
    require(Path('/usr/bin/python3.12').is_file() and shutil.which('gcc'),'system_python312_and_compiler_required')
    libc=platform.libc_ver();require(libc[0]=='glibc' and tuple(map(int,libc[1].split('.')[:2]))>=(2,28),'glibc_required')
    set_stage('source_integrity')
    for item in assets['files']:
        rel=Path(item['path']);require(not rel.is_absolute() and '..' not in rel.parts,'source_path');verify_file(root/rel,item)
    validate_model(model)
    set_stage('execution_authority')
    initialize_authority(execution_sha256)
    set_stage('model_manifest')
    require(len(model['artifacts'])==24 and sum(i['path'].endswith('.safetensors') for i in model['artifacts'])==17,'complete_model_required')
    set_stage('filesystem')
    evidence=root/'build-evidence';evidence.mkdir(exist_ok=True);(root/'tools').mkdir(exist_ok=True)
    require(not any(Path('/opt/venvs'/Path(e)).exists() for e in VERSIONS),'fresh_engine_environments_required')
    MODEL.mkdir(parents=True,exist_ok=True)
    set_stage('disk')
    require(shutil.disk_usage(MODEL).free>=sum(i['size_bytes'] for i in model['artifacts'])+40*1024**3,'setup_disk_capacity')
    set_stage('shared_memory')
    require(Path('/dev/shm').stat().st_mode and shutil.disk_usage('/dev/shm').total>=1024**3,'shared_memory_required')
    with (evidence/'bootstrap-private.log').open('xb') as log:
        set_stage('driver')
        driver=run(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader,nounits'],deadline,log,capture=True).decode().strip().splitlines()
        require(len(driver)==1 and 'H200' in driver[0],'single_h200_required');driver_version=driver[0].split(',')[1].strip();require(tuple(map(int,driver_version.split('.')))>=(580,65,6),'cuda13_driver_required')
        set_stage('uv')
        uv=assets['uv'];verify_file(root/uv['archive']['path'],uv['archive'])
        with tarfile.open(root/uv['archive']['path'],'r:gz') as archive:
            member=archive.getmember('uv-x86_64-unknown-linux-gnu/uv');require(member.isfile(),'uv_archive_member')
            stream=archive.extractfile(member);require(stream is not None,'uv_archive_member');(root/'tools/uv').write_bytes(stream.read())
        verify_file(root/'tools/uv',uv['binary']);(root/'tools/uv').chmod(0o755)
        require(run([str(root/'tools/uv'),'--version'],deadline,log,capture=True).decode().strip().startswith('uv 0.12.3'),'uv_version')
        for index,command in enumerate(install_commands(root,Path('/usr/bin/python3.12'))):
            set_stage('vllm_install' if index<2 else 'sglang_install');run(command,deadline,log)
        gpu=[]
        for engine,version in VERSIONS.items():
            python=f'/opt/venvs/{engine}/bin/python'
            set_stage(engine+'_dependency_validation')
            report=run([python,str(root/'src/runpod_benchmark/dependency_validator.py'),'--runtime',engine,'--lock',str(root/f'locks/{engine}.lock')],deadline,log,capture=True)
            require(json.loads(report)['status']=='pass','dependency_closure_failed');(evidence/f'{engine}-bootstrap-dependencies.json').write_bytes(report)
            set_stage(engine+'_gpu_self_test')
            gpu.append(json.loads(run([python,'-c',GPU_PROBE,engine,version],deadline,log,capture=True)))
        set_stage('model_download')
        run(['/opt/venvs/vllm/bin/python','-c',DOWNLOAD,str(root/'bootstrap-assets.json'),str(MODEL)],deadline,log)
        set_stage('model_integrity')
        for item in model['artifacts']:deadline.remaining();verify_file(MODEL/item['path'],item,deadline)
        set_stage('control_install')
        for source,target in [('control.sh','episode2-control')]:
            shutil.copyfile(root/f'runtime/{source}',Path('/usr/local/bin')/target);(Path('/usr/local/bin')/target).chmod(0o755)
        require(not Path('/run/episode2/process.json').exists(),'existing_control_process')
        set_stage('receipt')
        receipt={'schema_version':'episode2.direct-ssh-bootstrap-result.v1','status':'pass','execution_sha256':execution_sha256,'source_sha256':assets['source_sha256'],'assets_sha256':hashlib.sha256((root/'bootstrap-assets.json').read_bytes()).hexdigest(),'model_revision':REVISION,'model_artifacts_verified':len(model['artifacts']),'runtime_gpu_self_tests':gpu,'driver_version':driver_version,'setup_elapsed_seconds':time.monotonic()-deadline.start,'setup_remaining_seconds':deadline.remaining(),'service_ready':False,'gpu_serving':'unverified','native_metrics':'unverified','tool_smoke':'unverified'}
        (evidence/'bootstrap-result.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');return receipt

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,default=Path('/opt/episode2'));parser.add_argument('--timeout-seconds',type=int,default=1800);parser.add_argument('--execution-sha256',required=True);args=parser.parse_args()
    try:result=bootstrap(args.bundle,args.timeout_seconds,args.execution_sha256)
    except Exception as exc:
        print(json.dumps(safe_failure(exc,BOOTSTRAP_STAGE)));return 1
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
