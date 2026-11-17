"""Fixed image control rejects unbound requests and arbitrary engine commands."""
import importlib.util
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / 'runtime/episode2/control.py'


def control():
    assert PATH.is_file(), 'Episode02 image control payload is missing'
    spec=importlib.util.spec_from_file_location('episode2_image_control', PATH)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(operation='inventory', **fields):
    return {'operation':operation,'execution_sha256':'a'*64,'epoch_id':'epoch-001',
            'timeout_seconds':30,**fields}


@pytest.mark.parametrize('operation',['inventory','status','stop','start','tokenize','export'])
def test_closed_typed_operations_bind_execution_and_epoch(operation):
    module=control()
    fields={'engine':'vllm','common_overrides':{}} if operation=='start' else {}
    if operation=='tokenize': fields={'engine':'vllm','messages':[{'role':'user','content':'hello'}], 'tools':[]}
    if operation=='export': fields={'kind':'engine_log','max_bytes':4096}
    assert module.validate_request(request(operation,**fields),'a'*64)['operation']==operation


@pytest.mark.parametrize('fields', [{'command':'curl x'}, {'execution_sha256':'b'*64}, {'epoch_id':'../x'},
                                    {'timeout_seconds':True}, {'timeout_seconds':601}, {'engine':'unknown'}])
def test_unbound_or_undeclared_control_input_fails(fields):
    module=control()
    with pytest.raises(ValueError): module.validate_request(request(**fields),'a'*64)


def test_fixed_engine_argv_declares_tool_compatibility_preserving_performance_defaults():
    module=control()
    assert module.launch_arguments('vllm',{}) == ['/opt/venvs/vllm/bin/python','/opt/episode2/runtime/engine_launcher.py','vllm',
        '--model','/opt/models/qwen2.5-32b-instruct','--host','127.0.0.1','--port','8000',
        '--served-model-name','episode2-model','--enable-auto-tool-choice','--tool-call-parser','hermes']
    assert module.launch_arguments('sglang',{}) == ['/opt/venvs/sglang/bin/python','/opt/episode2/runtime/engine_launcher.py','sglang',
        '--model-path','/opt/models/qwen2.5-32b-instruct','--host','127.0.0.1','--port','8000',
        '--served-model-name','episode2-model','--tool-call-parser','qwen25']


@pytest.mark.parametrize('overrides',[{'gpu_memory_utilization':.8},{'trust_remote_code':True},
                                    {'model':'/tmp/x'}, {'max_model_len':'$(bad)'}])
def test_launch_does_not_accept_performance_flags_or_shell_text(overrides):
    module=control()
    with pytest.raises(ValueError): module.launch_arguments('vllm',overrides)


def test_duplicate_nonfinite_and_large_json_are_rejected():
    module=control()
    for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b' '*(1024*1024+1)]:
        with pytest.raises(ValueError): module.loads_request(raw)


@pytest.mark.skipif(not Path('/proc/self/stat').exists(),reason='Linux proc identity is checked in image CPU rehearsal')
def test_actual_proc_parser_preserves_birth_identity():
    import os
    module=control()
    observed=module.proc_identity(os.getpid())
    assert observed['pid']==os.getpid()
    assert isinstance(observed['starttime_ticks'],int) and observed['starttime_ticks']>0


def test_entrypoint_missing_bound_authority_exits_before_ssh():
    import subprocess
    entry=PATH.with_name('entrypoint.sh')
    assert entry.is_file(), 'Episode02 bound SSH entrypoint is missing'
    result=subprocess.run(['/bin/sh',str(entry)],env={'PATH':'/usr/bin:/bin'},capture_output=True,timeout=3)
    assert result.returncode!=0
    assert b'sshd' not in result.stderr


def test_observational_launcher_emits_values_from_returned_native_config():
    from types import SimpleNamespace
    path=PATH.with_name('engine_launcher.py')
    assert path.is_file(), 'actual native config observer is missing'
    spec=importlib.util.spec_from_file_location('episode2_launcher',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    scheduler=SimpleNamespace(max_num_batched_tokens=8192,max_num_seqs=1024,enable_chunked_prefill=True,
        policy='fcfs',async_scheduling=True,scheduler_cls=None)
    cache=SimpleNamespace(enable_prefix_caching=True,gpu_memory_utilization=.92,num_gpu_blocks=None,block_size=16)
    config=SimpleNamespace(scheduler_config=scheduler,cache_config=cache)
    observed=module.configuration_observation(config,'a'*64,'epoch-001')
    assert observed['schema_version']=='episode2.native-effective-config.v1'
    assert observed['config']=={'max_num_batched_tokens':8192,'max_num_seqs':1024,'enable_chunked_prefill':True,
        'scheduling_policy':'fcfs','async_scheduling':True,'scheduler_cls':None,'enable_prefix_caching':True,
        'gpu_memory_utilization':.92,'num_gpu_blocks':None,'block_size':16}
    assert cache.num_gpu_blocks is None


def test_start_persistence_failure_terminates_its_actual_new_process(tmp_path,monkeypatch):
    import os,signal,subprocess,sys
    module=control(); created=[]; original=subprocess.Popen
    def launch(*args,**kwargs):
        process=original(*args,**kwargs);created.append(process);return process
    # Only GPU prerequisites and Linux metadata are fixture inputs; the spawned
    # process, failure while committing ownership, and cleanup are real.
    monkeypatch.setattr(module,'gpu_pids',lambda _:[])
    monkeypatch.setattr(module,'gpu_inventory',lambda _: {})
    monkeypatch.setattr(module,'port_open',lambda:False)
    monkeypatch.setattr(module,'proc_identity',lambda _: {'starttime_ticks':1})
    original_read=Path.read_text
    def read(path,*args,**kwargs):
        if str(path)=='/proc/sys/kernel/random/boot_id':return 'test-boot'
        return original_read(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(module,'launch_arguments',lambda *_:[sys.executable,'-c','import time;time.sleep(60)'])
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    (tmp_path/'process.json.new').write_text('existing')
    try:
        with pytest.raises(FileExistsError):
            module.Controller(state=tmp_path).start(request('start',engine='vllm',common_overrides={}))
        assert len(created)==1
        assert created[0].poll() is not None, 'failed start leaked its uncommitted engine process'
    finally:
        for process in created:
            if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=3)


def test_control_argv_hash_matches_protocol_semantic_document_digest():
    from runpod_benchmark.episode2_contract import document_digest
    module=control();argv=module.launch_arguments('vllm',{})
    assert module.digest(module.canonical(argv))==document_digest(argv)


def test_bounded_probe_interruption_reaps_its_actual_child(monkeypatch):
    import os,signal,subprocess,sys
    module=control();created=[];original=subprocess.Popen
    def launch(*args,**kwargs):
        process=original(*args,**kwargs);created.append(process)
        def interrupted(*a,**kw):raise ValueError('test_interrupt')
        process.communicate=interrupted
        return process
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    try:
        with pytest.raises(ValueError,match='test_interrupt'):
            module.run([sys.executable,'-c','import time;time.sleep(60)'],1)
        assert created[0].poll() is not None,'interrupted control probe leaked its child'
    finally:
        for process in created:
            if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=3)


def test_usage_parsers_require_actual_closed_native_numbers():
    module=control()
    assert module.parse_gpu_usage(b'GPU-test, 47, 120000, 21000\n')=={'uuid':'GPU-test',
        'utilization_percent':47.0,'memory_used_bytes':120000*1024*1024,'memory_free_bytes':21000*1024*1024}
    assert module.parse_gpu_processes(b'42, 1200\n')==[{'pid':42,'gpu_memory_bytes':1200*1024*1024}]
    assert module.host_memory('MemTotal: 1000 kB\nMemAvailable: 250 kB\n')=={'memory_total_bytes':1024000,'memory_available_bytes':256000}
    assert module.cpu_ticks('cpu 1 2 3 4 5 6 7 8 100 200\n')==(36,9)
    for raw in [b'GPU-test, N/A, 120000, 21000\n',b'GPU-test, 101, 1, 2\n',b'GPU-test, 1, -1, 2\n']:
        with pytest.raises(ValueError):module.parse_gpu_usage(raw)
    with pytest.raises(ValueError):module.parse_gpu_processes(b'42, [Not Supported]\n')
    with pytest.raises(ValueError):module.host_memory('MemTotal: 1000 kB\nMemAvailable: 1001 kB\n')


def test_tokenize_requests_id_list_from_current_transformers_contract(monkeypatch):
    import io,sys
    from types import SimpleNamespace
    module=control()
    class Tokenizer:
        chat_template='tool-aware-template'
        def apply_chat_template(self,messages,*,tokenize,return_dict=True,**kwargs):
            if not tokenize:return 'rendered actual input'
            return {'input_ids':[2,3,5]} if return_dict else [2,3,5]
    transformer=SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a,**kw:Tokenizer()))
    monkeypatch.setitem(sys.modules,'transformers',transformer)
    def execute(argv,timeout,*,data):
        output=io.StringIO()
        with monkeypatch.context() as scope:
            scope.setattr(sys,'stdin',io.StringIO(data.decode()))
            scope.setattr(sys,'stdout',output)
            exec(argv[-1],{})
        return output.getvalue().encode()
    monkeypatch.setattr(module,'run',execute)
    result=module.Controller().tokenize({'engine':'vllm','messages':[{'role':'user','content':'hello'}],'tools':[],'timeout_seconds':30})
    assert result['token_count']==3


@pytest.mark.parametrize('engine',['vllm','sglang'])
def test_start_prepends_selected_runtime_bin_for_native_jit(tmp_path,monkeypatch,engine):
    module=control();captured={}
    monkeypatch.setattr(module,'gpu_pids',lambda _:[])
    monkeypatch.setattr(module,'gpu_inventory',lambda _: {})
    monkeypatch.setattr(module,'port_open',lambda:False)
    monkeypatch.setenv('PATH','/usr/bin:/bin')
    def launch(*args,**kwargs):
        captured.update(kwargs['env']);raise RuntimeError('stop_before_process_creation')
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    with pytest.raises(RuntimeError,match='stop_before_process_creation'):
        module.Controller(state=tmp_path).start(request('start',engine=engine,common_overrides={}))
    assert captured['PATH']==f'/opt/venvs/{engine}/bin:/usr/bin:/bin'


def inventory_fixture(tmp_path,monkeypatch):
    import hashlib,json
    module=control();root=tmp_path/'payload';model=tmp_path/'model';state=tmp_path/'state'
    root.mkdir();model.mkdir();state.mkdir(mode=0o700);(root/'build-evidence').mkdir()
    items=[]
    for i in range(24):
        name=f'model-{i:02}.safetensors' if i<17 else f'config-{i:02}.json'
        raw=f'{i:02}'.encode();(model/name).write_bytes(raw)
        items.append({'path':name,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    manifest={'model':{'revision':'a'*40,'artifacts':items},'source':{'tree_sha256':'b'*64}}
    (root/'payload-manifest.json').write_text(json.dumps(manifest))
    for engine in ('vllm','sglang'):(root/'build-evidence'/f'{engine}-defaults.json').write_text('{}')
    monkeypatch.setattr(module,'MODEL',model);monkeypatch.setattr(module,'gpu_inventory',lambda _: {})
    original=Path.open;reads=[]
    def track(path,*args,**kwargs):
        if path.parent==model and args and args[0]=='rb':reads.append(path.name)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',track)
    return module.Controller(root=root,state=state),model,state,root,reads


def test_model_cache_reuses_actual_hashes_only_for_unchanged_identity(tmp_path,monkeypatch):
    import os
    controller,model,state,root,reads=inventory_fixture(tmp_path,monkeypatch)
    first=controller.inventory(request());assert len(reads)==24
    second=controller.inventory(request());assert second==first and len(reads)==24
    cache=state/'model-integrity-cache.json';assert cache.stat().st_mode & 0o777 == 0o600
    changed=model/'model-00.safetensors';old=changed.stat();changed.write_bytes(b'xx')
    os.utime(changed,ns=(old.st_atime_ns,old.st_mtime_ns))
    with pytest.raises(ValueError,match='model_artifact_mismatch'):controller.inventory(request())
    assert len(reads)>24,'ctime mutation reused stale model verification'


def test_model_cache_plan_and_full_manifest_bindings_force_reverification(tmp_path,monkeypatch):
    import json
    controller,model,state,root,reads=inventory_fixture(tmp_path,monkeypatch)
    controller.inventory(request());assert len(reads)==24
    controller.inventory(request(execution_sha256='b'*64));assert len(reads)==48
    p=root/'payload-manifest.json';manifest=json.loads(p.read_text());manifest['source']['tree_sha256']='c'*64;p.write_text(json.dumps(manifest))
    controller.inventory(request(execution_sha256='b'*64));assert len(reads)==72


@pytest.mark.parametrize('engine',['vllm','sglang'])
def test_remote_tokenize_applies_native_tool_model_dump_before_template(monkeypatch,engine):
    import io,sys
    from types import SimpleNamespace
    module=control();raw={'type':'function','function':{'name':'lookup_inventory','parameters':{'type':'object'}}}
    normalized={'type':'function','function':{'name':'lookup_inventory','description':None,'parameters':{'type':'object'}}}
    if engine=='sglang':normalized['function']['strict']=False;normalized['defer_loading']=None
    seen=[]
    class Native:
        @classmethod
        def model_validate(cls,value):seen.append(value);return SimpleNamespace(model_dump=lambda:normalized)
    native_path='sglang.srt.entrypoints.openai.protocol' if engine=='sglang' else 'vllm.entrypoints.openai.chat_completion.protocol'
    monkeypatch.setitem(sys.modules,native_path,SimpleNamespace(Tool=Native,ChatCompletionToolsParam=Native))
    class Tokenizer:
        chat_template='native-tool-template'
        def apply_chat_template(self,messages,*,tokenize,**kwargs):
            assert kwargs['tools']==[normalized]
            return [1,2,3] if tokenize else 'native rendered actual input'
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a,**kw:Tokenizer())))
    def execute(argv,timeout,*,data):
        output=io.StringIO()
        with monkeypatch.context() as scope:
            scope.setattr(sys,'stdin',io.StringIO(data.decode()));scope.setattr(sys,'stdout',output);exec(argv[-1],{})
        return output.getvalue().encode()
    monkeypatch.setattr(module,'run',execute)
    result=module.Controller().tokenize({'engine':engine,'messages':[{'role':'user','content':'look up widget'}],'tools':[raw],'timeout_seconds':30})
    assert seen==[raw] and result['token_count']==3
