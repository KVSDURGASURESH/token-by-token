import importlib.util
from pathlib import Path
import pytest

PATH=Path(__file__).resolve().parents[1]/'runtime/episode2/bootstrap.py'
def bootstrap():
    assert PATH.is_file(), 'fixed direct SSH bootstrap missing'
    spec=importlib.util.spec_from_file_location('bootstrap',PATH);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_fixed_commands_pin_python_and_hash_locked_isolated_environments():
    m=bootstrap();commands=m.install_commands(Path('/opt/episode2'),Path('/usr/bin/python3.12'))
    assert len(commands)==4
    for engine,offset in [('vllm',0),('sglang',2)]:
        assert commands[offset]==['/opt/episode2/tools/uv','venv','--python','/usr/bin/python3.12','--no-python-downloads',f'/opt/venvs/{engine}']
        assert commands[offset+1]==['/opt/episode2/tools/uv','pip','sync','--python',f'/opt/venvs/{engine}/bin/python','--require-hashes','--index-strategy','unsafe-best-match','--only-binary',':all:',f'/opt/episode2/locks/{engine}.lock']

@pytest.mark.parametrize('seconds',[0,1801,True,-1])
def test_setup_deadline_rejects_unbounded_values(seconds):
    with pytest.raises(ValueError):bootstrap().Deadline(seconds)

def test_setup_deadline_expiry_never_starts_next_command():
    m=bootstrap();clock=iter([0,2]);d=m.Deadline(1,clock=lambda:next(clock))
    with pytest.raises(TimeoutError):d.remaining()

def test_model_manifest_rejects_unbound_revision_paths_duplicates_and_hashes():
    m=bootstrap();good={'repository':'Qwen/Qwen2.5-32B-Instruct','revision':'5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd','artifacts':[{'path':'config.json','size_bytes':1,'sha256':'a'*64}]}
    m.validate_model(good)
    for changed in [{**good,'revision':'main'},{**good,'repository':'other/model'},{**good,'artifacts':[{'path':'../key','size_bytes':1,'sha256':'a'*64}]},{**good,'artifacts':good['artifacts']*2}]:
        with pytest.raises(ValueError):m.validate_model(changed)

def test_partial_or_changed_model_bytes_fail_hash_gate(tmp_path):
    m=bootstrap();p=tmp_path/'config.json';p.write_bytes(b'bad')
    with pytest.raises(ValueError):m.verify_file(p,{'size_bytes':3,'sha256':'a'*64})

def test_no_generic_shell_or_serving_launch_in_bootstrap():
    text=PATH.read_text()
    assert 'shell=True' not in text
    assert 'enable-auto-tool-choice' not in text
    assert 'create_pod' not in text
    assert 'service_ready' in text


def test_typed_execution_authority_rejects_bad_sha_and_writes_correct_marker(tmp_path):
    m=bootstrap()
    for value in ('', 'x'*64, 'a'*63):
        with pytest.raises(ValueError):m.initialize_authority(value,tmp_path/'state')
    state=tmp_path/'state';m.initialize_authority('a'*64,state)
    assert (state/'execution-sha256').read_text()=='a'*64+'\n'
    assert state.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError):m.initialize_authority('b'*64,state)


def test_failure_diagnostic_retains_own_code_stage_and_never_raw_external_message():
    m=bootstrap()
    with pytest.raises(ValueError) as observed:m.require(False,'setup_disk_capacity')
    failure=m.safe_failure(observed.value,'disk')
    assert failure['error_code']=='setup_disk_capacity' and failure['stage']=='disk'
    secret='token_secret_value credential https://private.example/'
    failure=m.safe_failure(ValueError(secret),'host_prerequisites')
    assert secret not in str(failure)
    assert failure['error_code']=='bootstrap_unexpected_error'
    failure=m.safe_failure(FileNotFoundError(secret),'source_integrity')
    assert failure['error_code']=='required_file_missing'
    assert secret not in str(failure)


def test_gpu_probe_loaders_match_actual_pinned_linux_engine_sources():
    import ast,os
    root=os.environ.get('EPISODE2_PINNED_VENVS')
    if root is None:pytest.skip('requires retained exact Linux runtime artifacts')
    m=bootstrap();tree=ast.parse(m.GPU_PROBE)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='import_module']
    assert len(calls)==1 and isinstance(calls[0].args[0],ast.IfExp)
    choices={'vllm':calls[0].args[0].body.value,'sglang':calls[0].args[0].orelse.value}
    for engine,module in choices.items():
        site=Path(root)/engine/'lib/python3.12/site-packages';relative=Path(*module.split('.'))
        source=site/relative.with_suffix('.py')
        if not source.exists():source=site/relative/'__init__.py'
        assert source.is_file(),f'probe names unavailable module {module}'
    vllm=Path(root)/'vllm/lib/python3.12/site-packages/vllm'
    assert 'current_platform.import_kernels()' in (vllm/'_custom_ops.py').read_text()
    assert 'import vllm._C_stable_libtorch' in (vllm/'platforms/cuda.py').read_text()
    assert list(vllm.glob('_C_stable_libtorch*.so'))
    sg=Path(root)/'sglang/lib/python3.12/site-packages/sgl_kernel'
    assert 'common_ops = _load_architecture_specific_ops()' in (sg/'__init__.py').read_text()
    assert 'compute_capability == 90' in (sg/'load_utils.py').read_text()
    assert list((sg/'sm90').glob('common_ops*.so'))


def test_setup_deadline_supports_declared_1200_and_bounded_1800():
    m=bootstrap()
    assert m.Deadline(1200,clock=lambda:0).remaining()==1200
    assert m.Deadline(1800,clock=lambda:0).remaining()==1800
