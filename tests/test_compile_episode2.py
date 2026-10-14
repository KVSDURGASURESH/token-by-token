from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import json

import pytest

from runpod_benchmark.episode2_corpus import build_trace, make_synthetic_protocol
from runpod_benchmark.episode2_preflight import compile_episode2

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("episode2_test_compiler", ROOT / "scripts/compile_plan.py")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


@pytest.mark.parametrize('field', ['continuous_batching', 'chunked_prefill', 'prefix_caching'])
def test_native_auto_requires_validated_v2_default_binding(monkeypatch, field):
    fixture_spec = importlib.util.spec_from_file_location('native_auto_fixture', ROOT / 'tests/test_episode2_guard_boundaries.py')
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    manifest, live = fixture.execution_inputs(local_guard=False)
    manifest['execution']['runtimes'][0]['optimizations'][field] = 'native-auto'
    with pytest.raises(TypeError, match=field):
        compiler.compile_plan(manifest, live)
    from runpod_benchmark import episode2_preflight as preflight_module
    validations = []
    monkeypatch.setattr(preflight_module, 'validate_binding', lambda *a, **k: validations.append('binding'))
    monkeypatch.setattr(preflight_module, 'validate_manifest_binding', lambda *a, **k: validations.append('manifest'))
    monkeypatch.setattr(preflight_module, 'validate_live_binding', lambda *a, **k: validations.append('live'))
    manifest.update(schema_version=2, episode2={})
    plan = compiler.compile_plan(manifest, live)
    assert validations == ['binding', 'manifest', 'live']
    assert plan['manifest']['execution']['runtimes'][0]['optimizations'][field] == 'native-auto'
    manifest['execution']['runtimes'][0]['optimizations'][field] = 'pretend-verified'
    with pytest.raises(TypeError, match=field):
        compiler.compile_plan(manifest, live)


def test_v2_retains_full_pinned_dependency_inventory_with_bounded_limit(monkeypatch):
    fixture_spec = importlib.util.spec_from_file_location('dependency_inventory_fixture', ROOT / 'tests/test_episode2_guard_boundaries.py')
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    manifest, live = fixture.execution_inputs(local_guard=False)
    dependencies = [{'name': f'package-{i}', 'version': '1.0.0'} for i in range(243)]
    manifest['execution']['runtimes'][0]['dependencies'] = dependencies
    with pytest.raises(ValueError, match='dependencies'):
        compiler.compile_plan(manifest, live)
    from runpod_benchmark import episode2_preflight as preflight_module
    monkeypatch.setattr(preflight_module, 'validate_binding', lambda *a, **k: None)
    monkeypatch.setattr(preflight_module, 'validate_manifest_binding', lambda *a, **k: None)
    monkeypatch.setattr(preflight_module, 'validate_live_binding', lambda *a, **k: None)
    manifest.update(schema_version=2, episode2={})
    plan = compiler.compile_plan(manifest, live)
    assert plan['manifest']['execution']['runtimes'][0]['dependencies'] == dependencies
    manifest['execution']['runtimes'][0]['dependencies'] = dependencies * 3
    with pytest.raises(ValueError, match='512'):
        compiler.compile_plan(manifest, live)


def planning_inputs(protocol):
    now = datetime.now(timezone.utc)
    time = {"observed_at": now.isoformat().replace("+00:00", "Z"), "expires_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")}
    # Fake test quotes are explicitly synthetic; they are never provider evidence.
    live = {
        "gpu": {"gpu_id": "NVIDIA H200", "hourly_usd": "1.00", "stock": "available", "cloud": "SECURE", "region": "test-region", "datacenter": "test-dc", "source": "synthetic_mock", **time},
        "account": {"balance_usd": "13.00", "auto_recharge_verified_disabled": True},
        "estimate": {"expected_minutes": 30, "maximum_minutes": 60},
        "compatibility": {"status": "pass", "evidence": ["synthetic_mock"]},
        "ancillary_costs": {"source": "synthetic_mock", **time, "components": {name: {"status": "included", "amount_usd": "0.00"} for name in ("storage", "network_volume", "endpoint_public_ip", "egress", "image_pull", "startup", "other")}},
    }
    return {
        "schema_version": "episode2.inputs.v1", "classification": "synthetic_mock",
        "experiment_id": "episode2-defaults-test", "budget": {"max_usd": "10.00", "minimum_final_balance_usd": "3.00"},
        "live_inputs": live, "capability": {}, "trace": build_trace(protocol),
        "request_timeout_seconds": 10, "expected_minutes": 20,
        "runtime_start_timeout_seconds": 15, "readiness_timeout_seconds": 2,
        "admission": {"max_inflight": 2, "overflow": "wait_until_slot", "predecessor_failure": "block_dependents"},
        "resource": {"gpu_id": "NVIDIA H200", "gpu_count": 1, "cloud": "SECURE", "regions": ["test-region"], "datacenters": ["test-dc"], "container_disk_gb": 150, "volume_gb": 0, "network_volume_gb": 0},
        "phase_budgets": {"provision_seconds": 30, "image_pull_seconds": 30, "model_load_seconds": 180, "readiness_seconds": 30, "smoke_seconds": 1440, "warmup_seconds": 120, "benchmark_seconds": 840, "retry_seconds": 0, "export_seconds": 120, "teardown_seconds": 120},
        "fast_start": {"setup_to_first_smoke_seconds": 900, "smoke_seconds": 120, "dependency_installation": False, "engine_order": ["vllm", "sglang"], "fail_fast_gates": ["image", "model", "endpoint", "telemetry", "disk", "contract"], "on_failure": "terminate"},
    }


def test_planning_compilation_embeds_contract_and_cannot_approve():
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    plan = compile_episode2(protocol, inputs, {}, {}, planning_only=True)
    assert plan["schema_version"] == 2
    assert plan["execution_ready"] is False
    assert plan["manifest"]["episode2"]["protocol"] == protocol
    assert plan["manifest"]["episode2"]["trace"] == inputs["trace"]
    with pytest.raises(ValueError):
        compiler.approval_phrase(plan)
    assert compiler.validate_approval(plan, "APPROVE RUNPOD BENCHMARK anything MAX_USD 10.00") is False


def test_direct_bootstrap_phase_is_bound_costed_and_cannot_be_hidden():
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['fast_start'].update(route='direct_ssh_bootstrap',dependency_installation=True)
    inputs['phase_budgets']['bootstrap_seconds']=500
    material={'route':'direct_ssh_bootstrap','cache':{'mode':'direct_download','verified':False}}
    first=compile_episode2(protocol,inputs,material,{},planning_only=True)
    assert first['cost']['maximum_billable_minutes']==__import__('math').ceil(sum(inputs['phase_budgets'].values())/60)
    changed=deepcopy(inputs);changed['phase_budgets']['bootstrap_seconds']=501
    second=compile_episode2(protocol,changed,material,{},planning_only=True)
    assert compiler.plan_digest(first)!=compiler.plan_digest(second)
    changed['phase_budgets']['bootstrap_seconds']=900
    with pytest.raises(ValueError,match='setup'):compile_episode2(protocol,changed,material,{},planning_only=True)
    changed=deepcopy(inputs);changed['fast_start'].pop('route')
    with pytest.raises(ValueError):compile_episode2(protocol,changed,material,{},planning_only=True)


def test_planning_digest_binds_fast_start_and_complete_material():
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    first = compile_episode2(protocol, inputs, {}, {}, planning_only=True)
    changed = deepcopy(inputs)
    changed["phase_budgets"]["image_pull_seconds"] += 1
    second = compile_episode2(protocol, changed, {}, {}, planning_only=True)
    assert compiler.plan_digest(first) != compiler.plan_digest(second)


@pytest.mark.parametrize("change", ["cap", "reserve", "cost_component", "stale", "autopay", "stock", "trace", "setup", "smoke", "install", "benchmark", "warmup", "gpu", "two_hours", "startups", "readiness", "admission"])
def test_invalid_cost_and_fast_start_bindings_fail_closed(change):
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    if change == "cap":
        inputs["budget"]["max_usd"] = "0.01"
    elif change == "reserve":
        inputs["live_inputs"]["gpu"]["hourly_usd"] = "30.00"
    elif change == "cost_component":
        del inputs["live_inputs"]["ancillary_costs"]["components"]["image_pull"]
    elif change == "stale":
        inputs["live_inputs"]["gpu"]["observed_at"] = "2000-01-01T00:00:00Z"
    elif change == "autopay":
        inputs["live_inputs"]["account"]["auto_recharge_verified_disabled"] = False
    elif change == "stock":
        inputs["live_inputs"]["gpu"]["stock"] = "unknown"
    elif change == "trace":
        inputs["trace"]["logical_sha256"] = "0" * 64
    elif change == "setup":
        inputs["phase_budgets"]["image_pull_seconds"] = 900
    elif change == "smoke":
        inputs["fast_start"]["smoke_seconds"] = 301
    elif change == "install":
        inputs["fast_start"]["dependency_installation"] = True
    elif change == "benchmark":
        inputs["phase_budgets"]["benchmark_seconds"] = 839
    elif change == "warmup":
        inputs["phase_budgets"]["warmup_seconds"] = 119
    elif change == "gpu":
        inputs["live_inputs"]["gpu"]["gpu_id"] = "wrong"
    elif change == "two_hours":
        inputs["phase_budgets"]["retry_seconds"] = 7200
    elif change == "startups":
        inputs["phase_budgets"]["model_load_seconds"] = 179
    elif change == "readiness":
        inputs["phase_budgets"]["readiness_seconds"] = 23
    elif change == "admission":
        inputs["admission"]["max_inflight"] = 4
    with pytest.raises(ValueError):
        compile_episode2(protocol, inputs, {}, {}, planning_only=True)


def test_direct_setup_1800_and_engine_smoke_cost_preserve_six_measured_blocks():
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['request_timeout_seconds']=20
    inputs['runtime_start_timeout_seconds']=120;inputs['readiness_timeout_seconds']=5
    inputs['fast_start'].update(route='direct_ssh_bootstrap',dependency_installation=True,setup_to_first_smoke_seconds=1800)
    inputs['phase_budgets'].update(provision_seconds=30,image_pull_seconds=60,bootstrap_seconds=1200,
        model_load_seconds=1440,readiness_seconds=60,smoke_seconds=240,warmup_seconds=240,
        benchmark_seconds=1680,export_seconds=90,teardown_seconds=150)
    material={'route':'direct_ssh_bootstrap'}
    plan=compile_episode2(protocol,inputs,material,{},planning_only=True)
    assert sum(inputs['phase_budgets'].values())==5190
    assert plan['cost']['maximum_billable_minutes']==87
    envelope=plan['manifest']['episode2']['workload_envelope']
    assert envelope['model_turns']==144 and envelope['smoke_model_turns']==8
    assert protocol['repetition_blocks']==6
    changed=deepcopy(inputs);changed['phase_budgets']['smoke_seconds']=239
    with pytest.raises(ValueError,match='smoke'):
        compile_episode2(protocol,changed,material,{},planning_only=True)
    changed=deepcopy(inputs);changed['fast_start']['setup_to_first_smoke_seconds']=1801
    with pytest.raises(ValueError):
        compile_episode2(protocol,changed,material,{},planning_only=True)


def test_declared_cold_start_surplus_is_paid_once_per_engine_and_bounds_setup():
    from runpod_benchmark.episode2_preflight import engine_start_timeout_seconds
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['request_timeout_seconds']=20
    inputs['runtime_start_timeout_seconds']=120;inputs['readiness_timeout_seconds']=5
    inputs['fast_start'].update(route='direct_ssh_bootstrap',dependency_installation=True,setup_to_first_smoke_seconds=1800)
    inputs['phase_budgets'].update(provision_seconds=30,image_pull_seconds=60,bootstrap_seconds=1200,
        model_load_seconds=1680,readiness_seconds=60,smoke_seconds=240,warmup_seconds=240,
        benchmark_seconds=1680,export_seconds=60,teardown_seconds=150)
    assert engine_start_timeout_seconds(inputs,12,True)==240
    assert engine_start_timeout_seconds(inputs,12,False)==120
    material={'route':'direct_ssh_bootstrap'}
    plan=compile_episode2(protocol,inputs,material,{},planning_only=True)
    assert sum(inputs['phase_budgets'].values())==5400
    assert plan['cost']['maximum_billable_minutes']==90
    assert plan['manifest']['episode2']['workload_envelope']['model_turns']==144
    changed=deepcopy(inputs);changed['fast_start']['setup_to_first_smoke_seconds']=1534
    with pytest.raises(ValueError,match='setup phases'):
        compile_episode2(protocol,changed,material,{},planning_only=True)
    for budget in (1439,1681):
        changed=deepcopy(inputs);changed['phase_budgets']['model_load_seconds']=budget
        changed['fast_start'].pop('route')
        with pytest.raises(ValueError,match='cold'):
            engine_start_timeout_seconds(changed,12,True)


def test_direct_startup_pool_is_global_bounded_without_promising_all_timeout_maxima():
    from runpod_benchmark.episode2_preflight import engine_start_timeout_seconds
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['request_timeout_seconds']=20
    inputs['runtime_start_timeout_seconds']=240;inputs['readiness_timeout_seconds']=5
    inputs['fast_start'].update(route='direct_ssh_bootstrap',dependency_installation=True,setup_to_first_smoke_seconds=1800)
    inputs['phase_budgets'].update(provision_seconds=30,image_pull_seconds=60,bootstrap_seconds=480,
        model_load_seconds=840,readiness_seconds=60,smoke_seconds=240,warmup_seconds=240,
        benchmark_seconds=1680,export_seconds=30,teardown_seconds=150)
    assert engine_start_timeout_seconds(inputs,12,True)==240
    assert engine_start_timeout_seconds(inputs,12,False)==240
    material={'route':'direct_ssh_bootstrap'}
    plan=compile_episode2(protocol,inputs,material,{},planning_only=True)
    assert sum(inputs['phase_budgets'].values())==3810
    assert plan['cost']['maximum_billable_minutes']==64
    assert plan['manifest']['episode2']['workload_envelope']['model_turns']==144
    assert inputs['phase_budgets']['model_load_seconds'] < 12*inputs['runtime_start_timeout_seconds']
    changed=deepcopy(inputs);changed['phase_budgets']['model_load_seconds']=479
    with pytest.raises(ValueError,match='startup pool'):
        engine_start_timeout_seconds(changed,12,True)
    changed=deepcopy(inputs);changed['fast_start'].pop('route');changed['fast_start']['dependency_installation']=False
    changed['phase_budgets'].pop('bootstrap_seconds')
    with pytest.raises(ValueError,match='cold startup'):
        compile_episode2(protocol,changed,{}, {},planning_only=True)


def test_direct_shared_benchmark_allowance_preserves_work_and_global_spend_bound():
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['request_timeout_seconds']=20
    inputs['runtime_start_timeout_seconds']=240;inputs['readiness_timeout_seconds']=5
    inputs['fast_start'].update(route='direct_ssh_bootstrap',dependency_installation=True,setup_to_first_smoke_seconds=1800)
    inputs['phase_budgets'].update(provision_seconds=30,image_pull_seconds=60,bootstrap_seconds=480,
        model_load_seconds=480,readiness_seconds=60,smoke_seconds=240,warmup_seconds=240,
        benchmark_seconds=1200,export_seconds=30,teardown_seconds=150)
    inputs['budget']['minimum_final_balance_usd']='3.15'
    inputs['live_inputs']['account']['balance_usd']='7.756421'
    inputs['live_inputs']['gpu']['hourly_usd']='5.29'
    inputs['live_inputs']['ancillary_costs']['components']['storage']={'status':'billed','hourly_usd':'0.029762'}
    material={'route':'direct_ssh_bootstrap'}
    plan=compile_episode2(protocol,inputs,material,{},planning_only=True)
    assert sum(inputs['phase_budgets'].values())==2970
    assert plan['cost']['maximum_billable_minutes']==50
    assert plan['cost']['maximum_usd']=='4.43'
    envelope=plan['manifest']['episode2']['workload_envelope']
    assert envelope['model_turns']==144 and envelope['benchmark_seconds_minimum']==1680
    assert protocol['repetition_blocks']==6 and inputs['request_timeout_seconds']==20
    changed=deepcopy(inputs);changed['phase_budgets']['benchmark_seconds']=279
    with pytest.raises(ValueError,match='benchmark'):
        compile_episode2(protocol,changed,material,{},planning_only=True)
    changed=deepcopy(inputs);changed['fast_start'].pop('route');changed['fast_start']['dependency_installation']=False
    changed['phase_budgets'].pop('bootstrap_seconds');changed['phase_budgets']['model_load_seconds']=2880
    with pytest.raises(ValueError,match='benchmark'):
        compile_episode2(protocol,changed,{}, {},planning_only=True)
    changed=deepcopy(inputs);changed['live_inputs']['account']['balance_usd']='7.50'
    with pytest.raises(ValueError):
        compile_episode2(protocol,changed,material,{},planning_only=True)


def test_version_one_canonical_plan_is_unchanged():
    manifest = json.loads((ROOT / "manifests/h100-qwen32b-planning.json").read_text())
    live = json.loads((ROOT / "examples/planning-live-inputs.json").read_text())
    # Captured from the unchanged authoritative v1 compiler before this extension.
    assert compiler.plan_digest(compiler.compile_plan(manifest, live)) == "166e440549260df384e81be2cae7a9c7227c6eefa7b7c75db69710aa067b0aa3"


def test_full_schedule_is_bound_and_recomputed():
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    plan = compile_episode2(protocol, inputs, {}, {}, planning_only=True)
    assert len(plan["manifest"]["episode2"]["schedule"]) == 12
    damaged = deepcopy(plan)
    damaged["manifest"]["episode2"]["schedule"][0]["engine"] = "other"
    assert compiler.validate_approval(damaged, "anything") is False
    with pytest.raises(ValueError):
        compiler.plan_digest(damaged)


def test_live_cost_inputs_cannot_replace_the_embedded_quote():
    protocol = make_synthetic_protocol()
    plan = compile_episode2(protocol, planning_inputs(protocol), {}, {}, planning_only=True)
    changed = deepcopy(plan)
    changed["live_inputs"]["gpu"]["hourly_usd"] = "0.01"
    with pytest.raises(ValueError):
        compiler.compile_plan(changed["manifest"], changed["live_inputs"])


def test_mock_13_balance_rejects_10_01_exposure_with_3_reserve():
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    inputs["budget"]["max_usd"] = "10.01"
    inputs["live_inputs"]["gpu"]["hourly_usd"] = "12.251"
    with pytest.raises(ValueError, match="reserve"):
        compile_episode2(protocol, inputs, {}, {}, planning_only=True)


def test_first_smoke_deadline_counts_first_start_while_costing_all_restarts():
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    inputs["runtime_start_timeout_seconds"] = 100
    inputs["phase_budgets"]["model_load_seconds"] = 1200
    plan = compile_episode2(protocol, inputs, {}, {}, planning_only=True)
    assert plan["execution_ready"] is False
    assert plan["cost"]["maximum_billable_minutes"] == 66


def test_private_cli_exclusive_checkpoint_and_duplicate_keys(tmp_path):
    import os
    import subprocess
    protocol = make_synthetic_protocol()
    inputs = planning_inputs(protocol)
    for name, value in (("protocol", protocol), ("inputs", inputs), ("material", {}), ("cleanup", {})):
        file = tmp_path / f"{name}.json"
        file.write_text(json.dumps(value))
        file.chmod(0o600)
    tmp_path.chmod(0o700)
    command = [__import__("sys").executable, str(ROOT / "scripts/compile_episode2_execution.py")]
    for name in ("protocol", "inputs", "material", "cleanup"):
        command += [f"--{name}", str(tmp_path / f"{name}.json")]
    output = tmp_path / "compiled.json"
    command += ["--output", str(output), "--planning-only"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(output.read_text())
    assert envelope["plan"]["execution_ready"] is False
    assert envelope["approval_phrase"] is None
    assert output.stat().st_mode & 0o777 == 0o600
    retained = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert output.read_bytes() == retained
    output.unlink()
    (tmp_path / "material.json").write_text('{"images":{},"images":{}}')
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert not output.exists()
    (tmp_path / "material.json").write_text('{}')
    alias = tmp_path.parent / "private-input-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    alias_command = [part.replace(str(tmp_path), str(alias)) for part in command]
    assert subprocess.run(alias_command, capture_output=True).returncode == 2
    assert not output.exists()


def test_smoke_phase_costs_all_epochs_separately_from_first_fail_fast_window():
    protocol=make_synthetic_protocol();inputs=planning_inputs(protocol)
    inputs['phase_budgets']['smoke_seconds']=inputs['fast_start']['smoke_seconds']
    with pytest.raises(ValueError,match='smoke'):
        compile_episode2(protocol,inputs,{}, {},planning_only=True)
