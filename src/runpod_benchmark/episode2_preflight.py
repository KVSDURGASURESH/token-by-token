"""Provider-free Episode 02 contract, preparation gates, and cost compilation.

This module never builds, provisions, arms a watchdog, or requests approval.
Recorded evidence must be supplied by the private operator after integration.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from pathlib import Path
import stat
import time
from typing import Any, Mapping

from .episode2_contract import canonical_bytes, document_digest, require, validate_protocol, validate_trace

ROOT = Path(__file__).resolve().parents[2]
PHASES = (
    "provision_seconds", "image_pull_seconds", "model_load_seconds", "readiness_seconds",
    "smoke_seconds", "warmup_seconds", "benchmark_seconds", "retry_seconds",
    "export_seconds", "teardown_seconds",
)
FAIL_FAST_GATES = ["image", "model", "endpoint", "telemetry", "disk", "contract"]
DIRECT_BOOTSTRAP_NETWORK_SOURCES=['https://pypi.org','https://files.pythonhosted.org','https://download.pytorch.org',
    'https://huggingface.co','https://cas-bridge.xethub.hf.co','https://cas-server.xethub.hf.co','https://transfer.xethub.hf.co']
DIRECT_BOOTSTRAP_POST_CREATE_GATES=['bootstrap-source','dependencies','model','tokenizer','gpu','endpoint','telemetry','disk','contract']
CODE_FILES = (
    "scripts/compile_plan.py", "src/runpod_benchmark/episode2_preflight.py",
    "src/runpod_benchmark/episode2_contract.py", "src/runpod_benchmark/episode2_corpus.py",
    "src/runpod_benchmark/episode2_runner.py", "src/runpod_benchmark/episode2_schedule.py",
    "src/runpod_benchmark/streaming.py", "scripts/local_watchdog.py", "scripts/arm_local_watchdogs.py",
    "scripts/build_episode2_inputs.py", "scripts/validated_plan.py",
    "pyproject.toml", "uv.lock", "client/pyproject.toml", "client/requirements-build.lock",
)
_HASH_CACHE: dict[tuple, str] = {}
INTEGRITY_POLICY = {"max_files": 10000, "max_file_bytes": 64 * 1024**3, "max_total_bytes": 512 * 1024**3, "max_hash_seconds": 300, "reuse": "same_fd_stat_identity_mtime_ctime_size"}


def _closed(value: Any, fields: set[str], name: str) -> None:
    require(isinstance(value, Mapping) and set(value) == fields, f"invalid {name} fields")


def _positive(value: Any, name: str, *, zero: bool = False) -> int:
    require(type(value) is int and (0 if zero else 1) <= value <= 1_000_000, f"invalid {name}")
    return value


def _compiler():
    spec = importlib.util.spec_from_file_location("episode2_repository_compiler", ROOT / "scripts/compile_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engine_start_timeout_seconds(inputs: Mapping, schedule_count: int, first_for_engine: bool) -> int:
    """Spend declared startup surplus once per engine, without extending phases."""
    count = _positive(schedule_count, 'startup schedule count')
    require(type(first_for_engine) is bool, 'first engine startup must be boolean')
    engines = inputs['fast_start']['engine_order']
    require(engines == ['vllm', 'sglang'] and count >= len(engines), 'cold startup engine order invalid')
    base = _positive(inputs['runtime_start_timeout_seconds'], 'runtime startup timeout')
    budget = _positive(inputs['phase_budgets']['model_load_seconds'], 'model load budget', zero=True)
    if inputs['fast_start'].get('route') == 'direct_ssh_bootstrap' and budget < count * base:
        # Direct bootstrap uses an aggregate startup allowance. Individual caps
        # may borrow unused campaign time; the original global guard never moves.
        require(budget >= len(engines) * base, 'startup pool omits first engine bounds')
        return base
    surplus = budget - count * base
    require(surplus >= 0 and surplus % len(engines) == 0, 'cold startup surplus must be nonnegative integral seconds per engine')
    return base + (surplus // len(engines) if first_for_engine else 0)


def workload_envelope(protocol: Mapping, trace: Mapping, *, request_timeout_seconds: int) -> dict:
    """Conservative level-by-level dependency waves; both engines, no retries."""
    validate_trace(trace, protocol)
    timeout = _positive(request_timeout_seconds, "request timeout")
    workflows = sum(len(block["workflows"]) for block in trace["blocks"])
    turns = sum(len(block["turns"]) for block in trace["blocks"])
    waves = 0
    for cell in protocol["cells"]:
        for block in trace["blocks"]:
            depths: dict[str, int] = {}
            pending = list(block["turns"])
            while pending:
                ready = [turn for turn in pending if turn["predecessor_id"] is None or turn["predecessor_id"] in depths]
                require(bool(ready), "dependency graph cannot be scheduled")
                for turn in ready:
                    depths[turn["logical_request_id"]] = 1 + depths.get(turn["predecessor_id"], 0)
                    pending.remove(turn)
            for depth in set(depths.values()):
                waves += math.ceil(sum(value == depth for value in depths.values()) / cell["concurrency"])
    multiplicity = 2  # Exactly one baseline arm per engine in this approval unit.
    return {
        "workflows": workflows * len(protocol["cells"]) * multiplicity,
        "model_turns": turns * len(protocol["cells"]) * multiplicity,
        "class_workflows": {name: protocol["mixture"]["units_per_class"] * protocol["repetition_blocks"] * len(protocol["cells"]) * multiplicity for name in protocol["mixture"]["classes"]},
        "dependency_waves": waves * multiplicity,
        "benchmark_seconds_minimum": waves * multiplicity * timeout,
        "warmup_requests": protocol["warmup_reset"]["warmup_requests"] * protocol["repetition_blocks"] * len(protocol["cells"]) * multiplicity,
        "defaults_rechecks": protocol["repetition_blocks"] * multiplicity,
        "smoke_model_turns": 4 * multiplicity,
        "smoke_seconds_minimum": 4 * multiplicity * timeout,
        "total_model_turns": (turns + protocol["warmup_reset"]["warmup_requests"] * protocol["repetition_blocks"]) * len(protocol["cells"]) * multiplicity + 4 * multiplicity,
        "diagnostic_attempts": 0,
        "arms": ["vllm/defaults", "sglang/defaults"],
        "p99_status": "descriptive_until_1000_valid_observations_per_claim",
        "headline_percentile": "p95",
    }


def open_directory(root: Path) -> int:
    """Open a directory without following any symlink ancestor."""
    root = root.absolute()
    require(".." not in root.parts, "artifact root escapes")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def open_contained(root: Path, relative: Path) -> int:
    """Walk every ancestor using no-follow directory descriptors, then open file."""
    require(not relative.is_absolute() and ".." not in relative.parts, "artifact path escapes root")
    directory = open_directory(root)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _files_verified(entries: Any, root: Any, *, required_paths=()) -> bool:
    if not isinstance(entries, list) or not entries or not isinstance(root, str):
        return False
    try:
        require(len(entries) <= INTEGRITY_POLICY["max_files"], "artifact count exceeds bound")
        deadline = time.monotonic() + INTEGRITY_POLICY["max_hash_seconds"]
        seen = set()
        total = 0
        for entry in entries:
            _closed(entry, {"path", "sha256", "size_bytes"}, "artifact")
            relative = Path(entry["path"])
            require(not relative.is_absolute() and ".." not in relative.parts, "artifact path escapes root")
            require(entry["path"] not in seen, "duplicate artifact")
            seen.add(entry["path"])
            with os.fdopen(open_contained(Path(root), relative), "rb") as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and type(entry["size_bytes"]) is int and info.st_size == entry["size_bytes"] and info.st_size <= INTEGRITY_POLICY["max_file_bytes"], "artifact size/type mismatch")
                total += info.st_size
                require(total <= INTEGRITY_POLICY["max_total_bytes"], "artifact bytes exceed bound")
                identity = _identity(info)
                cached = _HASH_CACHE.get(identity)
                if cached is None:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        require(time.monotonic() <= deadline, "artifact integrity timeout")
                        digest.update(chunk)
                    cached = digest.hexdigest()
                require(_identity(os.fstat(stream.fileno())) == identity, "artifact changed while hashing")
                require(cached == entry["sha256"], "artifact hash mismatch")
                _HASH_CACHE[identity] = cached
        return set(required_paths) <= seen
    except (OSError, TypeError, ValueError):
        return False


def _static_verified(material, protocol):
    entries = material.get("static_attestations", [])
    root = material.get("artifact_root")
    if not _files_verified(entries, root):
        return False

    from .episode2_contract import loads_strict_json
    methods = {"gpu_driver": "runpod_readonly_catalog", "endpoint": "engine_cli_contract", "telemetry": "cpu_collector_selftest", "disk": "allocation_disk_contract", "defaults": "engine_cli_defaults", "model": "model_file_integrity", "tokenizer": "tokenizer_admission"}
    known = {entry["sha256"] for name in ("provider_evidence", "build_artifacts") for entry in material.get(name, [])}
    known |= {entry["sha256"] for entry in material.get("tokenizer", {}).get("admission_artifacts", [])}
    try:
        for entry in entries:
            with os.fdopen(open_contained(Path(root), Path(entry["path"])), "rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == entry["sha256"], "static attestation bytes mismatch")
            value = loads_strict_json(raw)
            _closed(value, {"schema_version", "scope", "gpu_id", "model_revision", "image_digests", "checks"}, "static attestation")
            require(value["schema_version"] == "episode2.static-attestation.v1" and value["scope"] == "precreation_static" and value["gpu_id"] == "NVIDIA H200", "static attestation scope mismatch")
            require(value["model_revision"] == protocol["material"]["model_revision"] and value["image_digests"] == {engine: protocol["material"][f"{engine}_image"] for engine in ("vllm", "sglang")}, "static material mismatch")
            _closed(value["checks"], set(methods), "static checks")
            for name, check in value["checks"].items():
                _closed(check, {"method", "artifact_sha256", "result"}, "static check")
                require(check["method"] == methods[name] and check["result"] == "pass" and check["artifact_sha256"] in known, "static check lacks actual retained source")
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _compiler_review_verified(material):
    review = material.get("compiler_review")
    if not isinstance(review, Mapping) or not _files_verified([review], material.get("artifact_root")):
        return False
    from .episode2_contract import loads_strict_json
    try:
        with os.fdopen(open_contained(Path(material["artifact_root"]), Path(review["path"])), "rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == review["sha256"], "review bytes changed")
        value = loads_strict_json(raw)
        _closed(value, {"schema_version", "status", "compiler_sha256", "schema_sha256", "installed_skill_compiler_sha256", "source_inventory_sha256"}, "compiler review")
        installed = Path.home() / ".codex/skills/runpod-inference-benchmark/scripts/compile_plan.py"
        return value["schema_version"] == "episode2.compiler-review.v1" and value["status"] == "compatible" and value["source_inventory_sha256"] == document_digest(material.get("code_files")) and all(value[field] == hashlib.sha256(path.read_bytes()).hexdigest() for field, path in (("compiler_sha256", ROOT / "scripts/compile_plan.py"), ("schema_sha256", ROOT / "schemas/episode2-execution.schema.json"), ("installed_skill_compiler_sha256", installed)))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def risk_scope_digest(experiment_id: str,protocol: Mapping,material: Mapping,resources: list,policy: Mapping) -> str:
    """Shared v2 scope identity; the independent owner response remains source=user."""
    return document_digest({'experiment_id':experiment_id,'protocol':protocol,'material':material,
        'resources':resources,'guard_hashes':policy['guard_hashes'],
        'owner_resolution_sha256':policy['owner_resolution_sha256']})


def validate_risk_scope_binding(experiment_id: str,protocol: Mapping,material: Mapping,cleanup: Mapping) -> None:
    from .episode2_contract import loads_strict_json
    entries=[entry for entry in material['provider_evidence'] if entry['path']=='cleanup-policy.json']
    require(len(entries)==1,'full cleanup policy required for risk scope')
    descriptor=open_contained(Path(material['artifact_root']),Path(entries[0]['path']))
    with os.fdopen(descriptor,'rb') as stream:raw=stream.read(65537)
    require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==entries[0]['sha256'],'cleanup scope artifact mismatch')
    policy=loads_strict_json(raw)
    require(cleanup['acknowledgment']['scope_sha256']==risk_scope_digest(experiment_id,protocol,material,cleanup['resources'],policy),'independent local risk scope mismatch')


DEFAULT_PARAMETER_KEYS={'scheduler','batching','cache','dependencies_sha256','help_sha256','default_launch_arguments_sha256','driver_requirement'}


def defaults_verified(engine: str,image: Mapping,material: Mapping) -> bool:
    """Reject inevitably invalid or unretained default captures before spending."""
    from .episode2_contract import HEX,loads_strict_json
    try:
        defaults=image.get('defaults');proof=image.get('default_proof')
        if not isinstance(defaults,dict) or set(defaults)!={'version','parameters'}:return False
        if defaults['version']!={'vllm':'0.29.0','sglang':'0.5.20'}.get(engine) or defaults['version']!=image.get('version'):return False
        parameters=defaults['parameters']
        if not isinstance(parameters,dict) or set(parameters)!=DEFAULT_PARAMETER_KEYS:return False
        if any(not isinstance(value,str) or not 1<=len(value)<=16384 for value in parameters.values()):return False
        if any(not HEX.fullmatch(parameters[key]) for key in ('dependencies_sha256','help_sha256','default_launch_arguments_sha256')):return False
        if not __import__('re').fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}',parameters['driver_requirement']):return False
        if not isinstance(proof,dict) or set(proof)!={'help','dependencies','launch_arguments'}:return False
        if any(entry not in material.get('build_artifacts',[]) for entry in proof.values()):return False
        if not _files_verified(list(proof.values()),material.get('artifact_root')):return False
        payloads={}
        for name,entry in proof.items():
            descriptor=open_contained(Path(material['artifact_root']),Path(entry['path']))
            with os.fdopen(descriptor,'rb') as stream:
                raw=stream.read(1024*1024+1)
            if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=entry['sha256']:return False
            payloads[name]=raw
        if parameters['help_sha256']!=proof['help']['sha256'] or parameters['dependencies_sha256']!=proof['dependencies']['sha256']:return False
        if not payloads['help'].decode('utf-8').strip():return False
        dependencies=loads_strict_json(payloads['dependencies']);arguments=loads_strict_json(payloads['launch_arguments'])
        if not isinstance(dependencies,list) or not any(isinstance(dep,dict) and dep.get('name')==engine and dep.get('version')==defaults['version'] for dep in dependencies):return False
        from .episode2_contract import TOOL_COMPATIBILITY_PROFILE,canonical_bytes
        compatibility=material.get('tool_compatibility')
        native=image.get('native_launch_arguments',image.get('launch_arguments'))
        if compatibility is not None:
            if canonical_bytes(compatibility)!=canonical_bytes(TOOL_COMPATIBILITY_PROFILE):return False
            if 'native_launch_arguments' not in image:return False
            common=material.get('common_launch_overrides',[])
            if image.get('launch_arguments')!=native+common+compatibility[engine]:return False
        elif native!=image.get('launch_arguments'):return False
        return dependencies==image.get('dependencies') and arguments==native and document_digest(arguments)==parameters['default_launch_arguments_sha256']
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):return False


def guard_scripts_verified(material: Mapping,policy: Mapping) -> bool:
    """Bind actual precreation guard implementation bytes, preserving legacy mode."""
    if not isinstance(policy,Mapping):return False
    runtime=material.get('guard_runtime')
    if runtime is None:
        return all(policy.get(key)==hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for key,path in (('watchdog_script_sha256','scripts/local_watchdog.py'),('launcher_script_sha256','scripts/arm_local_watchdogs.py')))
    if not isinstance(runtime,Mapping) or set(runtime)!={'watchdog','launcher','files'}:return False
    evidence=material.get('provider_evidence')
    if not isinstance(evidence,list):return False
    entries=runtime['files']
    if not isinstance(entries,list) or runtime['watchdog'] not in entries or runtime['launcher'] not in entries:return False
    unique=[]
    for entry in entries:
        if not isinstance(entry,dict) or entry not in evidence:return False
        if entry not in unique:unique.append(entry)
    if not _files_verified(unique,material.get('artifact_root')):return False
    return all(policy.get(role+'_script_sha256')==runtime[role]['sha256'] for role in ('watchdog','launcher'))


def direct_bootstrap_verified(protocol: Mapping,material: Mapping) -> bool:
    """Verify prepared fixed bytes; installed runtime/GPU observations come later."""
    from .episode2_contract import loads_strict_json
    try:
        profile=material.get('bootstrap')
        _closed(profile,{'schema_version','script','assets','bundle','source_sha256','dependency_locks',
            'model_artifacts_sha256','model_repository','model_revision','runtime_versions',
            'setup_deadline_seconds','network_sources','on_failure','dependency_installation',
            'post_create_verification','base_image','runtime_reference'},'bootstrap')
        require(material.get('route')=='direct_ssh_bootstrap' and profile['schema_version']=='episode2.direct-ssh-bootstrap.v1','bootstrap route mismatch')
        script=profile['script'];locks=profile['dependency_locks'];base=profile['base_image']
        _closed(locks,{'vllm','sglang'},'bootstrap locks')
        _closed(base,{'image_reference','image_digest','source','verified'},'base image')
        require(profile['network_sources']==DIRECT_BOOTSTRAP_NETWORK_SOURCES and
            profile['post_create_verification']==DIRECT_BOOTSTRAP_POST_CREATE_GATES and
            profile['on_failure']=='terminate' and profile['dependency_installation'] is True,'bootstrap fixed contract changed')
        require(type(profile['setup_deadline_seconds']) is int and 1<=profile['setup_deadline_seconds']<=1800,'bootstrap setup unbounded')
        require(script['path']=='runtime/episode2/bootstrap.py' and profile['source_sha256']==script['sha256'] and
            hashlib.sha256((ROOT/script['path']).read_bytes()).hexdigest()==script['sha256'],'bootstrap installed source mismatch')
        required=[script,*locks.values(),profile['runtime_reference']]
        require(all(entry in profile['assets'] for entry in required) and
            all(entry in material.get('build_artifacts',[]) for entry in profile['assets']),'bootstrap assets not retained')
        require(profile['bundle'] in material.get('build_artifacts',[]),'bootstrap archive not retained')
        require(base['source'] in material.get('provider_evidence',[]) and base['verified'] is True and
            isinstance(base['image_reference'],str) and base['image_reference'].endswith('@'+base['image_digest']) and
            base['image_digest']==protocol['material']['vllm_image']==protocol['material']['sglang_image'],'bootstrap base image not bound')
        require(profile['runtime_versions']=={'vllm':'0.29.0','sglang':'0.5.20'} and
            profile['model_repository']==protocol['material']['model_id'] and profile['model_revision']==protocol['material']['model_revision'] and
            profile['model_artifacts_sha256']==document_digest(material['model']['artifacts'])==protocol['material']['artifact_sha256'],'bootstrap model/runtime mismatch')
        require(_files_verified(list({entry['path']:entry for entry in profile['assets']+[profile['bundle'],base['source']]}.values()),material.get('artifact_root')),'bootstrap closure changed')
        for engine,name in [('vllm','vllm.lock'),('sglang','sglang-wheel.lock')]:
            require(locks[engine]['path']=='runtime/episode1/locks/'+name and
                locks[engine]['sha256']==hashlib.sha256((ROOT/locks[engine]['path']).read_bytes()).hexdigest(),'bootstrap pinned lock mismatch')
        with os.fdopen(open_contained(Path(material['artifact_root']),Path(profile['runtime_reference']['path'])),'rb') as stream:
            reference=loads_strict_json(stream.read(1024*1024+1))
        require(reference.get('schema_version')=='episode2.cpu-material-verification.v1' and
            reference.get('native_performance_defaults_preserved') is True and
            all(reference[e].get('imports_verified',0)>0 and 'sm_90' in reference[e].get('compiled_arch_flags','') for e in ('vllm','sglang')),'bootstrap runtime reference unverified')
        return True
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):return False


def preflight(protocol: Mapping, capability: Mapping, material: Mapping, cleanup: Mapping) -> dict:
    validate_protocol(protocol)
    require(all(isinstance(value, Mapping) for value in (capability, material, cleanup)), "preflight documents must be objects")
    blockers: list[str] = []
    def gate(name, passed):
        if not passed:
            blockers.append(name)
    gate("synthetic_mock", protocol["classification"] == "recorded")
    gate("protocol_material", protocol["material"]["execution_ready"] is True)
    numeric = {"e2e_slo_ms", "ttft_slo_ms", "tpot_slo_ms", "goodput_min_tokens_per_second", "admission_rate_min", "cost_max_usd", "resource_max"}
    gate("numeric_quality_slo_cost_resource_gates", numeric <= set(protocol["safeguards"]) and "output_length_tolerance_fraction" in protocol["quality"])
    gate("initial_scope", protocol["repetition_blocks"] == 6 and protocol["mixture"]["units_per_class"] == 1 and len(protocol["cells"]) == 1 and protocol["cells"][0]["mode"] == "closed-loop" and protocol["cells"][0]["concurrency"] == 2 and protocol["cells"][0]["temperature"] == "warm")
    gate("numeric_arrival_schedule", all(cell["mode"] == "closed-loop" for cell in protocol["cells"]))
    images = material.get("images", {})
    direct=material.get('route')=='direct_ssh_bootstrap'
    prepared=direct_bootstrap_verified(protocol,material) if direct else False
    if direct:gate('bootstrap_profile',prepared)
    gate("images", set(images) == {"vllm", "sglang"} and all(isinstance(images[engine], Mapping) and (prepared if direct else images[engine].get("verified") is True and images[engine].get("cpu_smoke_verified") is True and images[engine].get("hopper_supported") is True) and images[engine].get("image_digest") == protocol["material"][f"{engine}_image"] and images[engine].get("defaults_sha256") == protocol["material"][f"{engine}_defaults_sha256"] and document_digest(images[engine].get("defaults")) == images[engine].get("defaults_sha256") and defaults_verified(engine,images[engine],{**material,'tool_compatibility':protocol['material'].get('tool_compatibility'),'common_launch_overrides':protocol['material']['common_launch_overrides']}) for engine in images))
    gate("operator_image", material.get("operator_image", {}).get("verified") is True)
    artifact_root = material.get("artifact_root")
    gate("build_artifacts", _files_verified(material.get("build_artifacts"), artifact_root))
    model = material.get("model", {})
    gate("model_artifacts", model.get("repository") == protocol["material"]["model_id"] and model.get("revision") == protocol["material"]["model_revision"] and _files_verified(model.get("artifacts"), artifact_root) and document_digest(model.get("artifacts")) == protocol["material"]["artifact_sha256"])
    tokenizer = material.get("tokenizer", {})
    gate("tokenizer", _files_verified(tokenizer.get("artifacts"), artifact_root) and document_digest(tokenizer.get("artifacts")) == protocol["material"]["tokenizer_sha256"] and tokenizer.get("template_sha256") == protocol["material"]["template_sha256"] and tokenizer.get("token_bands_verified") is True)
    gate("tokenizer_admission", _files_verified(tokenizer.get("admission_artifacts"), artifact_root) and tokenizer.get("usage_must_match_admission") is True and any(entry.get("path") == tokenizer.get("template_path") and entry.get("sha256") == protocol["material"]["template_sha256"] for entry in tokenizer.get("artifacts", [])))
    required_code = set(CODE_FILES) | {str(path.relative_to(ROOT)) for pattern in ("src/runpod_benchmark/*.py", "schemas/episode2*.json") for path in ROOT.glob(pattern)}
    if direct:required_code|={'runtime/episode2/bootstrap.py','runtime/episode1/locks/vllm.lock','runtime/episode1/locks/sglang-wheel.lock'}
    gate("code_closure", _files_verified(material.get("code_files"), str(ROOT), required_paths=required_code))
    versions = __import__("importlib.metadata", fromlist=["version"])
    gate("compiler_dependency", material.get("compiler_dependencies") == {name: versions.version(name) for name in ("jsonschema", "attrs", "jsonschema-specifications", "referencing", "rpds-py")})
    gate("compiler_review", _compiler_review_verified(material))
    from .episode2_corpus import TOOL_FIXTURES
    gate("tool_fixtures", material.get("tool_fixtures") == TOOL_FIXTURES and document_digest(material.get("tool_fixtures")) == protocol["tool_fixtures_sha256"])
    gate("capability", capability.get("status") in {"static_verified", "provider_verified"} and capability.get("precreation_scope") == "static_readonly" and capability.get("protocol_sha256") == document_digest(protocol) and capability.get("model_id") == protocol["material"]["model_id"] and capability.get("gpu_id") == "NVIDIA H200" and capability.get("verified") is True)
    gate("static_attestations", _static_verified(material, protocol))
    for name in ("gpu_driver", "endpoint", "telemetry", "disk", "defaults"):
        gate(name, capability.get(f"{name}_verified") is True)
    gate("post_create_gpu_gate", capability.get("post_create_gpu_smoke_required") is True)
    gate("telemetry_contract", type(material.get("telemetry", {}).get("cadence_seconds")) is int and bool(material.get("telemetry", {}).get("collectors")))
    gate("evidence_closure", _files_verified(material.get("provider_evidence"), artifact_root) and capability.get("source") in {entry.get("path") for entry in material.get("provider_evidence", []) if isinstance(entry, Mapping)})
    mode = cleanup.get("mode")
    watchdog = cleanup.get("guard_policy") if mode == "local_only_acknowledged" else cleanup.get("independent_watchdog", {})
    gate("independent_watchdog", guard_scripts_verified(material,watchdog))
    resolution = cleanup.get("resolution", {})
    gate("cleanup", mode in {"provider_deadline", "local_only_acknowledged"} and resolution.get("verified") is True and resolution.get("action") == "terminate" and set(resolution.get("triggers", [])) == {"failure", "timeout", "export_failure", "interruption", "success"})
    gate("cleanup_resolution_artifact", any(resolution.get("source") in {entry.get("path"), entry.get("sha256")} for entry in material.get("provider_evidence", []) if isinstance(entry, Mapping)))
    cache = material.get("cache", {})
    network = cache.get("mode") == "network_volume"
    # Current backend has no verified pod+volume deadline/readback lifecycle.
    # Future support requires its own reviewed lifetime and guard contract.
    gate("cache_lifetime", not network)
    gate("cache", (prepared and cache.get('mode')=='direct_download' and cache.get('verified') is False) if direct else cache.get("verified") is True and cache.get("mode") in {"baked", "network_volume"} and (not network or (mode == "provider_deadline" and "network_volume" in cleanup.get("resources", []) and cache.get("datacenter") == capability.get("datacenter"))))
    if mode == "local_only_acknowledged":
        gate("guard_acknowledgment", cleanup.get("acknowledgment", {}).get("response") == "ACCEPT LOCAL-WATCHDOG RISK")
        from .episode2_contract import HEX
        scope=cleanup.get("acknowledgment", {}).get("scope_sha256")
        gate("guard_scope_binding", isinstance(scope,str) and HEX.fullmatch(scope) is not None)
        gate("guard_policy", isinstance(cleanup.get("guard_policy"), Mapping) and cleanup["guard_policy"].get("mode") == "local_only_acknowledged" and cleanup.get("resources") == ["pod"] and not network)
        for key, path in (("watchdog_script_sha256", "scripts/local_watchdog.py"), ("launcher_script_sha256", "scripts/arm_local_watchdogs.py")):
            gate(key, guard_scripts_verified(material,cleanup.get("guard_policy", {})))
    elif mode == "provider_deadline":
        deadline = cleanup.get("provider_deadline", {})
        gate("provider_deadline", deadline.get("verified") is True and isinstance(deadline.get("source"), str) and bool(deadline["source"]) and deadline.get("permanent_deletion") is True)
    return {"execution_ready": not blockers, "blockers": blockers, "provider_calls": 0}


def validate_binding(binding: Mapping, *, planning_only: bool) -> None:
    """Revalidate complete v2 canonical inputs every time approval is checked."""
    import json
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
    schema = json.loads((ROOT / "schemas/episode2-execution.schema.json").read_text())
    try:
        Draft202012Validator(schema).validate(binding)
    except ValidationError as exc:
        raise ValueError("invalid closed Episode 02 execution binding") from exc
    protocol, inputs = binding["protocol"], binding["inputs"]
    validate_protocol(protocol)
    validate_trace(binding["trace"], protocol)
    require(binding["integrity_policy"] == INTEGRITY_POLICY, "integrity policy changed")
    from .episode2_schedule import compile_order
    require(binding["schedule"] == compile_order(dict(protocol), ["defaults"]), "runtime schedule mismatch")
    require(binding["trace"] == inputs["trace"], "duplicate trace mismatch")
    require(binding["capability"] == inputs["capability"], "duplicate capability mismatch")
    fast, phases = inputs["fast_start"], inputs["phase_budgets"]
    direct=fast.get('route')=='direct_ssh_bootstrap'
    require(binding['material'].get('route','baked')==fast.get('route','baked'),'bootstrap route mismatch')
    _closed(phases, set(PHASES)|({'bootstrap_seconds'} if direct else set()), "phase budgets")
    for name, value in phases.items():
        _positive(value, name, zero=True)
    require(120 <= fast["smoke_seconds"] <= 300, "each engine smoke must be bound to 120-300 seconds")
    require(1 <= fast["setup_to_first_smoke_seconds"] <= 1800, "setup deadline exceeds 1800 seconds")
    first_smoke_setup = phases["provision_seconds"] + phases["image_pull_seconds"] + phases.get('bootstrap_seconds',0) + engine_start_timeout_seconds(inputs, len(binding['schedule']), True) + inputs["readiness_timeout_seconds"]
    require(first_smoke_setup <= fast["setup_to_first_smoke_seconds"], "setup phases exceed first-smoke deadline")
    require(fast["dependency_installation"] is direct and fast["engine_order"] == ["vllm", "sglang"] and fast["fail_fast_gates"] == FAIL_FAST_GATES and fast["on_failure"] == "terminate", "fast-start fail-fast contract changed")
    if direct:
        require(phases['bootstrap_seconds']>0,'bootstrap download/install phase missing')
        if not planning_only:
            require(binding['material']['bootstrap']['setup_deadline_seconds']==fast['setup_to_first_smoke_seconds'] and direct_bootstrap_verified(protocol,binding['material']),'fixed bootstrap proof missing')
    resource = inputs["resource"]
    require(resource["gpu_id"] == "NVIDIA H200" and resource["gpu_count"] == 1, "requires sequential single H200")
    live = inputs["live_inputs"]
    require(live["gpu"]["gpu_id"] == resource["gpu_id"] and live["gpu"]["cloud"] == resource["cloud"] and live["gpu"]["region"] in resource["regions"] and live["gpu"]["datacenter"] in resource["datacenters"], "GPU offer differs from selected target")
    envelope = workload_envelope(protocol, binding["trace"], request_timeout_seconds=inputs["request_timeout_seconds"])
    require(envelope == binding["workload_envelope"], "duplicate workload totals mismatch")
    require(fast['smoke_seconds'] >= 4 * inputs['request_timeout_seconds'], 'smoke window undercounts four requests')
    require(phases['smoke_seconds'] >= max(envelope['smoke_seconds_minimum'], len(fast['engine_order']) * fast['smoke_seconds']), 'smoke phase omits engine checks')
    benchmark_minimum = envelope["benchmark_seconds_minimum"]
    if direct:
        # One paired block fits this allowance; later blocks can use remaining
        # campaign time, without moving the original global money/deadline guard.
        benchmark_minimum = math.ceil(benchmark_minimum / protocol["repetition_blocks"])
    require(phases["benchmark_seconds"] >= benchmark_minimum, "benchmark budget undercounts dependency waves")
    require(phases["warmup_seconds"] >= envelope["warmup_requests"] * inputs["request_timeout_seconds"], "warmup budget undercounts request timeouts")
    if not direct:
        require(phases["model_load_seconds"] >= len(binding["schedule"]) * inputs["runtime_start_timeout_seconds"], "model load budget omits scheduled startups")
    require(phases["readiness_seconds"] >= len(binding["schedule"]) * inputs["readiness_timeout_seconds"], "readiness budget omits scheduled probes/default rechecks")
    require(inputs["admission"] == {"max_inflight": max(cell["concurrency"] for cell in protocol["cells"]), "overflow": "wait_until_slot", "predecessor_failure": "block_dependents"}, "admission differs from closed-loop concurrency/dependency contract")
    require(sum(phases.values()) <= 7200, "budget_blocked: phases exceed two-hour envelope")
    require(binding["hashes"] == {name: document_digest(binding[name]) for name in ("protocol", "trace", "material", "capability", "cleanup", "inputs")}, "contract hash mismatch")
    actual = preflight(protocol, binding["capability"], binding["material"], binding["cleanup"])
    require(binding["preflight"] == actual, "preflight status mismatch")
    if not planning_only:
        require(actual["execution_ready"] and inputs["classification"] == "recorded", "execution preflight incomplete")
        live = inputs["live_inputs"]
        sources = {entry["path"] for entry in binding["material"]["provider_evidence"]}
        require(live["gpu"]["source"] in sources and live["ancillary_costs"]["source"] in sources, "provider pricing source not retained")
        require(resource["datacenters"] == [live["gpu"]["datacenter"]] and binding["capability"]["datacenter"] == live["gpu"]["datacenter"], "capability datacenter mismatch")
        require(resource["network_volume_gb"] > 0 if binding["material"]["cache"]["mode"] == "network_volume" else resource["network_volume_gb"] == 0, "cache storage mismatch")
        from decimal import Decimal
        require(Decimal(protocol["safeguards"]["cost_max_usd"]) == Decimal(inputs["budget"]["max_usd"]), "protocol and owner cost cap mismatch")
        if binding['cleanup']['mode']=='local_only_acknowledged':
            validate_risk_scope_binding(inputs['experiment_id'],protocol,binding['material'],binding['cleanup'])
        policy = binding["cleanup"].get("guard_policy") if binding["cleanup"]["mode"] == "local_only_acknowledged" else binding["cleanup"]["independent_watchdog"]
        _compiler()._validate_guard_policy(policy, [{"id": "vllm"}, {"id": "sglang"}])
        horizon = policy["arming_timeout_seconds"] + policy["poll_interval_seconds"] + sum(policy["delete_retry_delays_seconds"]) + 4 * len(policy["delete_retry_delays_seconds"]) * policy["cli_timeout_seconds"]
        require(phases["teardown_seconds"] >= horizon, "teardown phase omits full watchdog CLI/retry horizon")
        require(phases["export_seconds"] > 0, "essential export must have an explicit budget")
        if binding["cleanup"]["mode"] == "provider_deadline":
            require(sum(phases.values()) <= binding["cleanup"]["provider_deadline"]["delete_after_seconds"] <= math.ceil(sum(phases.values()) / 60) * 60, "provider deletion deadline does not fit complete phase envelope")


def compile_episode2(protocol: Mapping, inputs: dict, material: dict, cleanup: dict, *, planning_only: bool = False) -> dict:
    validate_protocol(protocol)
    capability = inputs["capability"]
    status = preflight(protocol, capability, material, cleanup)
    planning_only = planning_only or not status["execution_ready"] or inputs["classification"] != "recorded"
    trace = inputs["trace"]
    from .episode2_schedule import compile_order
    binding = {"protocol": protocol, "trace": trace, "material": material, "capability": capability, "cleanup": cleanup, "inputs": inputs, "preflight": status, "integrity_policy": INTEGRITY_POLICY, "schedule": compile_order(dict(protocol), ["defaults"]), "workload_envelope": workload_envelope(protocol, trace, request_timeout_seconds=inputs["request_timeout_seconds"])}
    binding["hashes"] = {name: document_digest(binding[name]) for name in ("protocol", "trace", "material", "capability", "cleanup", "inputs")}
    validate_binding(binding, planning_only=planning_only)
    seconds = sum(inputs["phase_budgets"].values())
    maximum_minutes = math.ceil(seconds / 60)
    live = dict(inputs["live_inputs"])
    live["estimate"] = {"expected_minutes": inputs["expected_minutes"], "maximum_minutes": maximum_minutes}
    require(live["estimate"]["expected_minutes"] <= maximum_minutes, "expected estimate exceeds phase envelope")
    # Ancillary costs are validated even for incomplete-material planning.
    compiler = _compiler()
    compiler._validate_ancillary_costs(live.get("ancillary_costs"))
    manifest = _manifest_from_binding(binding, planning_only=planning_only)
    if not planning_only and cleanup["mode"] == "local_only_acknowledged":
        live["guard_acknowledgment"] = {key:cleanup["acknowledgment"][key] for key in ("response","source","observed_at")}
    return compiler.compile_plan(manifest, live)


def _manifest_from_binding(binding, *, planning_only):
    protocol, inputs, material, cleanup = (binding[name] for name in ("protocol", "inputs", "material", "cleanup"))
    maximum_minutes = math.ceil(sum(inputs["phase_budgets"].values()) / 60)
    runtime_versions = {engine: material.get("images", {}).get(engine, {}).get("version", "unresolved") for engine in ("vllm", "sglang")}
    manifest = {
        "schema_version": 2, "planning_only": planning_only, "experiment_id": inputs["experiment_id"],
        "budget": inputs["budget"], "resource": {"gpu_count": 1, "cloud": inputs["resource"]["cloud"], "terminate_after_minutes": maximum_minutes},
        "model": {"repository": protocol["material"]["model_id"], "revision": protocol["material"]["model_revision"]},
        "runtimes": [{"id": engine, "version": runtime_versions[engine], "fallbacks": []} for engine in ("vllm", "sglang")],
        "workload": {"cells": [{"input_tokens": spec["input_tokens_max"], "output_tokens": spec["requested_output_tokens"], "concurrency": cell["concurrency"], "requests": protocol["mixture"]["units_per_class"] * spec["turns"], "repetitions": protocol["repetition_blocks"], "timeout_seconds": inputs["request_timeout_seconds"]} for cell in protocol["cells"] for spec in protocol["mixture"]["classes"].values()]},
        "episode2": binding,
    }
    if not planning_only:
        manifest["execution"] = _execution_contract(protocol, inputs, material, cleanup, maximum_minutes)
    return manifest


def validate_manifest_binding(manifest):
    require(type(manifest.get("planning_only")) is bool, "planning_only must be boolean")
    expected = _manifest_from_binding(manifest["episode2"], planning_only=manifest["planning_only"])
    require(canonical_bytes(manifest) == canonical_bytes(expected), "version 2 summary differs from complete campaign binding")


def validate_live_binding(binding, live, *, planning_only):
    inputs = binding["inputs"]
    expected = dict(inputs["live_inputs"])
    expected["estimate"] = {"expected_minutes": inputs["expected_minutes"], "maximum_minutes": math.ceil(sum(inputs["phase_budgets"].values()) / 60)}
    if not planning_only and binding["cleanup"]["mode"] == "local_only_acknowledged":
        expected["guard_acknowledgment"] = {key:binding["cleanup"]["acknowledgment"][key] for key in ("response","source","observed_at")}
    require(canonical_bytes(live) == canonical_bytes(expected), "live pricing/guard inputs differ from embedded evidence")


def _execution_contract(protocol, inputs, material, cleanup, maximum_minutes):
    pmat, resource = protocol["material"], inputs["resource"]
    operator = material["operator_image"]
    runtimes = []
    for engine in ("vllm", "sglang"):
        image = material["images"][engine]
        runtimes.append({"id": engine, "version": image["version"], "dependencies": image["dependencies"], "launch_arguments": image["launch_arguments"], "backend": f"{engine}-openai", "optimizations": image["optimizations"], "fallback_policy": {"mode": "none", "max_attempts": 1}})
    contract = {
        "resource": {"gpu_id": resource["gpu_id"], "regions": resource["regions"], "datacenters": resource["datacenters"], "container": {"image_digest": operator["image_digest"], "cuda_version": operator["cuda_version"], "driver_requirement": operator["driver_requirement"]}, "storage": {key: resource[key] for key in ("container_disk_gb", "volume_gb", "network_volume_gb")}, "network": {"ports": [22], "public_ip": False, "egress_policy": "restricted" if material.get('route')=='direct_ssh_bootstrap' else "none"}},
        "model": {"tokenizer_repository": pmat["model_id"], "tokenizer_revision": pmat["model_revision"], "dtype": "bfloat16", "context_length": pmat["context_window"], "chat_template": {"revision": pmat["model_revision"], "sha256": pmat["template_sha256"]}},
        "runtimes": runtimes,
        "workload": {"dataset": {"source": "episode2.public.corpus.v1", "revision": document_digest(protocol), "sha256": document_digest(inputs["trace"])}, "prompt_cells": [{"id": f"{cell['cell_id']}-{name}", "prompt_sha256": document_digest(spec)} for cell in protocol["cells"] for name, spec in protocol["mixture"]["classes"].items()], "sampling": {"temperature": "0", "top_p": "1", "top_k": 0}, "seed": protocol["seed"], "warmup_requests": protocol["warmup_reset"]["warmup_requests"], "repetitions": protocol["repetition_blocks"], "timeout_seconds": inputs["request_timeout_seconds"], "load_mode": "closed-loop"},
        "quality_gates": {"minimum_success_rate": str(protocol["safeguards"]["quality_min"]), "maximum_error_rate": str(protocol["safeguards"]["error_rate_max"]), "maximum_p99_ms": int(protocol["safeguards"]["median_ceiling_ms"]), "output_validation": "episode2 canonical per-class semantics; p99 descriptive until eligible"},
        "telemetry": {"cadence_seconds": material["telemetry"]["cadence_seconds"], "collectors": material["telemetry"]["collectors"]},
        "teardown": {"delete_after_minutes": maximum_minutes, "resources": cleanup["resources"], "require_inventory_absent": True, "require_direct_lookup_not_found": True},
    }
    if cleanup["mode"] == "local_only_acknowledged":
        contract["guard_policy"] = cleanup["guard_policy"]
    return contract
