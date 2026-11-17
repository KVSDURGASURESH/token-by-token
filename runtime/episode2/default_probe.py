import os,ast,hashlib,importlib.metadata as md,inspect,json,pathlib,subprocess,sys
engine=sys.argv[1]; root=pathlib.Path(sys.argv[2] if len(sys.argv)>2 else '/opt/episode2/build-evidence')
def canonical(o):return (json.dumps(o,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
if engine=='vllm':
    from vllm.engine.arg_utils import EngineArgs
    args=EngineArgs(model='/opt/models/qwen2.5-32b-instruct')
    names=['scheduler_cls','scheduling_policy','max_num_batched_tokens','max_num_seqs','enable_prefix_caching','gpu_memory_utilization']
    values={n:getattr(args,n) for n in names}
    source=inspect.getsource(EngineArgs.get_batch_defaults)
    predicted={'evidence_class':'precreation_static','inputs':{'device_name':'NVIDIA H200','memory_branch':'70GiB<=total<160GiB','usage_context':'OPENAI_API_SERVER','world_size':1},'output':{'max_num_batched_tokens':8192,'max_num_seqs':1024},'unresolved':['actual_device_memory','effective_chunked_prefill','kv_cache_capacity','actual_free_memory']}
    # Assert this exact installed resolver includes the prediction branch. This
    # does not query or pretend to run a GPU.
    tree=ast.parse(inspect.cleandoc(source)); assert '"a100" not in device_name' in source
    assert 'UsageContext.OPENAI_API_SERVER: 8192' in source and 'UsageContext.OPENAI_API_SERVER: 1024' in source
else:
    from sglang.srt.server_args import ServerArgs
    args=ServerArgs(model_path='/opt/models/qwen2.5-32b-instruct')
    names=['schedule_policy','max_running_requests','chunked_prefill_size','disable_radix_cache','mem_fraction_static']
    values={n:getattr(args,n) for n in names}
    source=inspect.getsource(ServerArgs.resolve_once)
    predicted={'evidence_class':'precreation_static','inputs':{'resolution_policy':'installed_native_auto'},'output':None,'unresolved':[n for n,v in values.items() if v is None]+['actual_free_memory','kv_cache_capacity']}
(root/f'{engine}-default-resolver.py').write_text(source)
(root/f'{engine}-native-defaults.json').write_bytes(canonical({'raw_native_defaults':values,'resolver_sha256':sha(source.encode()),'prediction':predicted}))
module='vllm.entrypoints.openai.api_server' if engine=='vllm' else 'sglang.launch_server'
help_env={**os.environ,**({'VLLM_TARGET_DEVICE':'cpu'} if engine=='vllm' else {})}
help_run=subprocess.run([sys.executable,'-m',module,'--help'],capture_output=True,timeout=180,env=help_env)
assert help_run.returncode==0,(help_run.returncode,help_run.stderr[-2000:])
(root/f'{engine}-help.txt').write_bytes(help_run.stdout)
(root/f'{engine}-help-stderr.txt').write_bytes(help_run.stderr)
argv=[f'/opt/venvs/{engine}/bin/python','/opt/episode2/runtime/engine_launcher.py',engine,'--model' if engine=='vllm' else '--model-path','/opt/models/qwen2.5-32b-instruct','--host','127.0.0.1','--port','8000','--served-model-name','episode2-model']
inventory=json.loads((root/f'{engine}-dependencies-final.json').read_bytes())['inventory']
(root/f'{engine}-dependency-inventory.json').write_bytes(canonical(inventory))
(root/f'{engine}-launch-arguments.json').write_bytes(canonical(argv))
parameters={'scheduler':json.dumps({n:v for n,v in values.items() if 'schedul' in n},sort_keys=True,separators=(',',':')),
    'batching':json.dumps({n:v for n,v in values.items() if n in {'max_running_requests','chunked_prefill_size','max_num_batched_tokens','max_num_seqs'}},sort_keys=True,separators=(',',':')),
    'cache':json.dumps({n:v for n,v in values.items() if n in {'disable_radix_cache','enable_prefix_caching','mem_fraction_static','gpu_memory_utilization'}},sort_keys=True,separators=(',',':')),
    'help_sha256':sha(help_run.stdout),'dependencies_sha256':sha(canonical(inventory)),
    'driver_requirement':'580.65.06','default_launch_arguments_sha256':sha(canonical(argv).rstrip(b'\n'))}
evidence={'version':md.version(engine),'help_sha256':parameters['help_sha256'],'dependencies_sha256':parameters['dependencies_sha256'],
    'defaults':{'version':md.version(engine),'parameters':parameters},'default_launch_arguments':argv,
    'help_capture_environment':{'VLLM_TARGET_DEVICE':'cpu'} if engine=='vllm' else {},'defaults_evidence_class':'precreation_static','unresolved_fields':predicted['unresolved']}
(root/f'{engine}-defaults.json').write_bytes(canonical(evidence))
