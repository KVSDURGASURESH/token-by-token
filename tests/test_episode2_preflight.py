from copy import deepcopy

from runpod_benchmark.episode2_corpus import build_trace, make_synthetic_protocol
from runpod_benchmark.episode2_preflight import preflight, workload_envelope


def test_missing_material_never_reports_live_readiness():
    protocol = make_synthetic_protocol()
    result = preflight(protocol, {}, {}, {})
    assert result["execution_ready"] is False
    assert {"synthetic_mock", "images", "model_artifacts", "cleanup", "capability"} <= set(result["blockers"])


def test_envelope_retains_all_classes_blocks_and_dependency_waves():
    protocol = make_synthetic_protocol()
    result = workload_envelope(protocol, build_trace(protocol), request_timeout_seconds=10)
    assert result["workflows"] == 96
    assert result["model_turns"] == 144
    assert result["dependency_waves"] == 84
    assert result["benchmark_seconds_minimum"] == 840
    assert set(result["class_workflows"]) == set(protocol["mixture"]["classes"])


def test_execution_scope_rejects_unbound_bursts_and_nonbaseline_cells():
    protocol = make_synthetic_protocol(mode="open-loop")
    result = preflight(protocol, {}, {}, {})
    assert "numeric_arrival_schedule" in result["blockers"]
    protocol = make_synthetic_protocol()
    protocol["cells"][0]["concurrency"] = 4
    result = preflight(protocol, {}, {}, {})
    assert "initial_scope" in result["blockers"]


def test_bad_trace_cannot_be_substituted_for_its_hash():
    protocol = make_synthetic_protocol()
    trace = build_trace(protocol)
    trace["blocks"][0]["turns"][0]["messages_sha256"] = "0" * 64
    from pytest import raises
    with raises(ValueError):
        workload_envelope(protocol, trace, request_timeout_seconds=10)


def test_file_closure_hashes_actual_root_contained_bytes(tmp_path):
    import hashlib
    from runpod_benchmark.episode2_preflight import _files_verified
    asset = tmp_path / "asset.json"
    asset.write_bytes(b"{}")
    entry = {"path": "asset.json", "sha256": hashlib.sha256(b"{}").hexdigest(), "size_bytes": 2}
    assert _files_verified([entry], str(tmp_path)) is True
    asset.write_bytes(b"[]")
    assert _files_verified([entry], str(tmp_path)) is False
    asset.unlink()
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b"{}")
    asset.symlink_to(outside)
    assert _files_verified([entry], str(tmp_path)) is False
    assert _files_verified([{**entry, "path": "../outside.json"}], str(tmp_path)) is False


def test_preflight_requires_static_image_evidence_and_bound_post_create_gpu_gate():
    protocol = make_synthetic_protocol()
    result = preflight(protocol, {}, {}, {})
    assert {"build_artifacts", "post_create_gpu_gate", "independent_watchdog"} <= set(result["blockers"])


def test_file_closure_rejects_symlink_root_and_ancestor(tmp_path):
    import hashlib
    from runpod_benchmark.episode2_preflight import _files_verified
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "asset.json").write_bytes(b"{}")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    entry = {"path": "asset.json", "sha256": hashlib.sha256(b"{}").hexdigest(), "size_bytes": 2}
    assert _files_verified([entry], str(alias)) is False
    assert _files_verified([{**entry, "path": "alias/asset.json"}], str(tmp_path)) is False


def test_untyped_precreation_booleans_do_not_satisfy_static_proof():
    protocol = make_synthetic_protocol()
    result = preflight(protocol, {"status": "provider_verified", "gpu_driver_verified": True}, {}, {})
    assert "static_attestations" in result["blockers"]


def test_network_cache_requires_complete_billable_lifetime():
    protocol = make_synthetic_protocol()
    result = preflight(protocol, {}, {"cache": {"mode": "network_volume", "verified": True}}, {})
    assert "cache_lifetime" in result["blockers"]


def test_missing_compiler_compatibility_review_keeps_preparation_blocked():
    result = preflight(make_synthetic_protocol(), {}, {}, {})
    assert "compiler_review" in result["blockers"]


def test_actual_private_guard_binds_retained_bytes_and_both_policy_hashes(tmp_path):
    import hashlib
    from runpod_benchmark.episode2_preflight import guard_scripts_verified
    entries={}
    for role in ('watchdog','launcher'):
        raw=(role+' actual source').encode();(tmp_path/(role+'.py')).write_bytes(raw)
        entries[role]={'path':role+'.py','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}
    material={'artifact_root':str(tmp_path),'guard_runtime':dict(entries,files=list(entries.values())),'provider_evidence':list(entries.values())}
    policy={'watchdog_script_sha256':entries['watchdog']['sha256'],'launcher_script_sha256':entries['launcher']['sha256']}
    assert guard_scripts_verified(material,policy)
    changed=dict(policy);changed['watchdog_script_sha256']='0'*64
    assert not guard_scripts_verified(material,changed)
    (tmp_path/'watchdog.py').write_bytes(b'changed bytes')
    assert not guard_scripts_verified(material,policy)


def test_private_guard_cannot_use_unretained_or_symlink_source(tmp_path):
    import hashlib
    from runpod_benchmark.episode2_preflight import guard_scripts_verified
    source=tmp_path/'source.py';source.write_bytes(b'actual')
    entry={'path':'source.py','sha256':hashlib.sha256(b'actual').hexdigest(),'size_bytes':6}
    policy={'watchdog_script_sha256':entry['sha256'],'launcher_script_sha256':entry['sha256']}
    material={'artifact_root':str(tmp_path),'guard_runtime':{'watchdog':entry,'launcher':entry,'files':[entry]},'provider_evidence':[]}
    assert not guard_scripts_verified(material,policy)
    material['provider_evidence']=[entry];source.unlink();source.symlink_to(tmp_path.parent/'outside.py')
    assert not guard_scripts_verified(material,policy)


def test_guard_dependency_closure_includes_validated_plan():
    from runpod_benchmark.episode2_preflight import CODE_FILES
    assert 'scripts/validated_plan.py' in CODE_FILES


def test_empty_or_unretained_defaults_fail_before_creation(tmp_path):
    from runpod_benchmark.episode2_preflight import defaults_verified
    assert not defaults_verified('vllm',{'version':'0.29.0','defaults':{'version':'0.29.0','parameters':{}}},{'artifact_root':str(tmp_path),'build_artifacts':[]})


def test_direct_bootstrap_requires_exact_source_assets_and_post_create_contract(tmp_path,monkeypatch):
    import hashlib,json
    from copy import deepcopy
    from runpod_benchmark.episode2_contract import document_digest
    from runpod_benchmark import episode2_preflight as module
    protocol=make_synthetic_protocol();entries=[]
    for name in ['runtime/episode2/bootstrap.py','runtime/episode1/locks/vllm.lock','runtime/episode1/locks/sglang-wheel.lock','base-image.json','bootstrap-assets.json']:
        raw=name.encode();path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        entries.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)})
    monkeypatch.setattr(module,'ROOT',tmp_path)
    reference={'schema_version':'episode2.cpu-material-verification.v1','native_performance_defaults_preserved':True,
               'vllm':{'imports_verified':1,'compiled_arch_flags':'sm_90'},'sglang':{'imports_verified':1,'compiled_arch_flags':'sm_90'}}
    raw=json.dumps(reference).encode();(tmp_path/'runtime-reference.json').write_bytes(raw)
    runtime_ref={'path':'runtime-reference.json','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}
    protocol['material']['artifact_sha256']=document_digest([])
    protocol['material']['sglang_image']=protocol['material']['vllm_image']
    profile={'schema_version':'episode2.direct-ssh-bootstrap.v1','script':entries[0],
        'assets':entries[:3]+[entries[4],runtime_ref],'bundle':entries[4],'source_sha256':entries[0]['sha256'],'runtime_reference':runtime_ref,
        'dependency_locks':{'vllm':entries[1],'sglang':entries[2]},
        'model_artifacts_sha256':document_digest([]),'model_repository':protocol['material']['model_id'],
        'model_revision':protocol['material']['model_revision'],'runtime_versions':{'vllm':'0.29.0','sglang':'0.5.20'},
        'setup_deadline_seconds':900,'network_sources':module.DIRECT_BOOTSTRAP_NETWORK_SOURCES,
        'on_failure':'terminate','dependency_installation':True,
        'post_create_verification':module.DIRECT_BOOTSTRAP_POST_CREATE_GATES,
        'base_image':{'image_reference':'runpod/pytorch@'+protocol['material']['vllm_image'],
                      'image_digest':protocol['material']['vllm_image'],'source':entries[3],'verified':True}}
    material={'route':'direct_ssh_bootstrap','artifact_root':str(tmp_path),'bootstrap':profile,
              'model':{'artifacts':[]},'provider_evidence':[entries[3]],'build_artifacts':entries[:3]+[entries[4],runtime_ref]}
    assert module.direct_bootstrap_verified(protocol,material)
    for key,value in [('source_sha256','0'*64),('setup_deadline_seconds',1801),('on_failure','preserve'),
                      ('dependency_installation',False),('post_create_verification',[]),('network_sources',['https://arbitrary.example'])]:
        changed=deepcopy(material);changed['bootstrap'][key]=value
        assert not module.direct_bootstrap_verified(protocol,changed),key
    (tmp_path/entries[0]['path']).write_bytes(b'changed source')
    assert not module.direct_bootstrap_verified(protocol,material)



def test_default_proof_binds_closed_parameters_and_actual_source_bytes(tmp_path):
    import hashlib,json
    from runpod_benchmark.episode2_contract import document_digest
    from runpod_benchmark.episode2_preflight import defaults_verified
    values={'help':'vllm 0.29.0 native help','dependencies':[{'name':'vllm','version':'0.29.0'}],'launch_arguments':['serve','/opt/model']}
    entries={}
    for name,value in values.items():
        raw=value.encode() if name=='help' else json.dumps(value).encode()
        (tmp_path/(name+'.txt')).write_bytes(raw)
        entries[name]={'path':name+'.txt','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}
    image={'version':'0.29.0','dependencies':values['dependencies'],'launch_arguments':values['launch_arguments'],'default_proof':entries,'defaults':{'version':'0.29.0','parameters':{'scheduler':'fcfs','batching':'native_auto','cache':'native_auto','driver_requirement':'580.65.06','dependencies_sha256':entries['dependencies']['sha256'],'help_sha256':entries['help']['sha256'],'default_launch_arguments_sha256':document_digest(values['launch_arguments'])}}}
    material={'artifact_root':str(tmp_path),'build_artifacts':list(entries.values())}
    assert defaults_verified('vllm',image,material)
    from copy import deepcopy
    from runpod_benchmark.episode2_contract import TOOL_COMPATIBILITY_PROFILE
    compatible=deepcopy(image)
    compatible['native_launch_arguments']=deepcopy(values['launch_arguments'])
    compatible['launch_arguments']+=TOOL_COMPATIBILITY_PROFILE['vllm']
    declared={**material,'tool_compatibility':deepcopy(TOOL_COMPATIBILITY_PROFILE)}
    assert defaults_verified('vllm',compatible,declared)
    undeclared=deepcopy(compatible);undeclared['launch_arguments']+=['--max-num-seqs','7']
    assert not defaults_verified('vllm',undeclared,declared)
    assert not defaults_verified('vllm',compatible,material)
    compatible['native_launch_arguments']+=['--max-num-seqs','7']
    assert not defaults_verified('vllm',compatible,declared)
    image['defaults']['parameters']['unknown']=True
    assert not defaults_verified('vllm',image,material)
    del image['defaults']['parameters']['unknown'];(tmp_path/'help.txt').write_bytes(b'changed help')
    assert not defaults_verified('vllm',image,material)


def test_risk_scope_validates_exact_retained_policy_without_v1_source_change(tmp_path):
    import hashlib,json
    from runpod_benchmark.episode2_preflight import risk_scope_digest,validate_risk_scope_binding
    policy={'guard_hashes':{'watchdog':'a'*64},'owner_resolution_sha256':'b'*64}
    raw=json.dumps(policy).encode();(tmp_path/'cleanup-policy.json').write_bytes(raw)
    material={'artifact_root':str(tmp_path),'provider_evidence':[{'path':'cleanup-policy.json','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}]}
    cleanup={'mode':'local_only_acknowledged','resources':['pod'],'acknowledgment':{'source':'user','response':'ACCEPT LOCAL-WATCHDOG RISK','observed_at':'2026-10-13T00:00:00Z'}}
    protocol=make_synthetic_protocol();cleanup['acknowledgment']['scope_sha256']=risk_scope_digest('test',protocol,material,['pod'],policy)
    validate_risk_scope_binding('test',protocol,material,cleanup)
    cleanup['acknowledgment']['scope_sha256']='0'*64
    with __import__('pytest').raises(ValueError):validate_risk_scope_binding('test',protocol,material,cleanup)


def test_actual_guard_requires_retained_executable_dependency_closure(tmp_path):
    import hashlib
    from runpod_benchmark.episode2_preflight import guard_scripts_verified
    raw=b'guard source';(tmp_path/'guard.py').write_bytes(raw)
    entry={'path':'guard.py','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}
    policy={'watchdog_script_sha256':entry['sha256'],'launcher_script_sha256':entry['sha256']}
    material={'artifact_root':str(tmp_path),'guard_runtime':{'watchdog':entry,'launcher':entry},'provider_evidence':[entry]}
    assert not guard_scripts_verified(material,policy)


def test_envelope_counts_smoke_once_per_engine_and_keeps_all_measured_work():
    protocol=make_synthetic_protocol()
    result=workload_envelope(protocol,build_trace(protocol),request_timeout_seconds=10)
    assert result['smoke_model_turns']==8
    assert result['smoke_seconds_minimum']==80
    assert result['model_turns']==144
    assert result['defaults_rechecks']==12
    assert result['total_model_turns']==164


def test_live_acknowledgment_projects_user_fields_and_keeps_scope_in_binding():
    from runpod_benchmark.episode2_preflight import validate_live_binding
    ack={'response':'ACCEPT LOCAL-WATCHDOG RISK','source':'user','observed_at':'2026-10-13T00:00:00Z','scope_sha256':'a'*64}
    live={'gpu':{'source':'actual-retained-provider'},'guard_acknowledgment':{k:ack[k] for k in ('response','source','observed_at')},'estimate':{'expected_minutes':1,'maximum_minutes':1}}
    inputs={'live_inputs':{'gpu':live['gpu']},'expected_minutes':1,'phase_budgets':{'benchmark_seconds':60}}
    binding={'inputs':inputs,'cleanup':{'mode':'local_only_acknowledged','acknowledgment':ack}}
    validate_live_binding(binding,live,planning_only=False)
