"""Runs within the built image without network or GPU access."""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time


def canonical(obj): return (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def digest(raw): return hashlib.sha256(raw).hexdigest()
def command(argv): return subprocess.run(argv, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120).stdout
def require(value, reason):
    if not value: raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "cpu_startup_duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("cpu_startup_nonfinite_json")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cpu_startup_invalid_json") from exc


def bounded_bytes(path, limit):
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        require(size <= limit, "cpu_startup_contract_too_large")
        raw = stream.read(limit + 1)
        require(len(raw) == size and len(raw) <= limit, "cpu_startup_contract_changed_or_too_large")
        return raw


def _limit_control_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024, 64 * 1024))


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # EPERM proves that the process group may still exist.  Treating it as
        # absent would let a control probe leave descendants behind.
        return True


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        # A numeric PGID can outlive/reuse the leader identity. Fail closed
        # instead of retrying signals against a group we cannot authenticate.
        raise ValueError("control_startup_cleanup_not_permitted") from exc


def _cleanup_group(pgid, deadline):
    if not _group_exists(pgid):
        return
    if not _signal_group(pgid, signal.SIGTERM):
        return
    term_deadline = min(deadline, time.monotonic() + 0.2)
    while _group_exists(pgid) and time.monotonic() < term_deadline:
        time.sleep(0.01)
    if _group_exists(pgid):
        if not _signal_group(pgid, signal.SIGKILL):
            return
    while _group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.01)
    require(not _group_exists(pgid), "control_startup_cleanup_failed")


def control_command(argv, *, cwd="/opt/episode1", timeout=10, cleanup_reserve=1,
                    output_limit=64 * 1024):
    """Run a local control-plane probe with a wall timeout and bounded output."""
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1",
        "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "*", "no_proxy": "*",
    }
    operation_deadline = time.monotonic() + timeout + cleanup_reserve
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   env=env, cwd=cwd, start_new_session=True,
                                   preexec_fn=_limit_control_output)
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
        if timed_out:
            _signal_group(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=min(0.2, max(0.01, operation_deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                _signal_group(process.pid, signal.SIGKILL)
                process.wait(timeout=max(0.01, operation_deadline - time.monotonic()))
        descendants = _group_exists(process.pid)
        if descendants:
            _cleanup_group(process.pid, operation_deadline)
        if timed_out:
            raise ValueError("control_startup_timeout")
        if descendants:
            raise ValueError("control_startup_descendants")
        size = output.tell()
        require(size <= output_limit, "control_startup_output_limit")
        require(returncode == 0, "control_startup_failed")
        output.seek(0)
        return output.read(output_limit + 1)


def verify_control_startup(root):
    """Import the package and run a declared help-only entrypoint when present."""
    package_root = str(root)
    deny_network = ("import socket\n"
                    "def _denied(*a,**k): raise RuntimeError('network disabled in CPU smoke')\n"
                    "socket.create_connection=_denied\nsocket.getaddrinfo=_denied\nsocket.socket.connect=_denied\n")
    import_code = deny_network + "import sys;sys.path.insert(0," + repr(package_root) + ");import runpod_benchmark"
    control_command([sys.executable, "-I", "-c", import_code], cwd=package_root)
    contract_path = root / "materials/runtime/episode1/cpu-startup.json"
    require(contract_path.is_file() and not contract_path.is_symlink(), "cpu_startup_contract")
    contract = strict_json(bounded_bytes(contract_path, 4096))
    require(isinstance(contract, dict) and set(contract) == {"schema_version", "module", "argv"},
            "cpu_startup_contract")
    require(contract["schema_version"] == "episode1.cpu-startup.v1", "cpu_startup_contract")
    require(contract["argv"] == ["--help"], "cpu_startup_argv")
    require(contract["module"] == "runpod_benchmark.episode1_remote_control", "cpu_startup_module")
    invocation = (deny_network + "import runpy,sys;sys.path.insert(0," + repr(package_root) + ");"
                  "sys.argv=[" + repr(contract["module"]) + "]+" + repr(contract["argv"]) + ";"
                  "runpy.run_module(" + repr(contract["module"]) + ",run_name='__main__')")
    usage = control_command([sys.executable, "-I", "-c", invocation], cwd=package_root)
    try:
        usage_text = usage.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("cpu_startup_usage_encoding") from exc
    require(re.search(r"(?m)^usage:\s+\S+", usage_text) is not None, "cpu_startup_usage_missing")


def collect(expected):
    root = pathlib.Path("/opt/episode1")
    manifest = json.loads((root / "manifest.json").read_bytes())
    require(digest(canonical(manifest)) == expected, "manifest_digest")
    require(digest(pathlib.Path(__file__).read_bytes()) == manifest["tooling"]["cpu_smoke_sha256"], "smoke_code_digest")
    require(platform.system() == "Linux" and platform.machine() == "x86_64", "platform")
    require(platform.python_version_tuple()[:2] == ("3", "12"), "python")
    require(re.fullmatch(r"uv 0\.12\.3(?: \([^\n]*\))?", command(["uv", "--version"]).decode().strip()), "installer_version")
    require(digest(pathlib.Path("/usr/local/bin/uv").read_bytes()) == manifest["installer"]["sha256"], "installer_digest")
    require(not list(pathlib.Path("/etc/ssh").glob("ssh_host_*")), "baked_host_keys")
    require(not pathlib.Path("/root/.ssh/authorized_keys").exists(), "baked_authorized_keys")
    require(not pathlib.Path("/root/.cache/uv").exists(), "installer_cache")
    observed_materials = []
    for item in manifest["materials"]:
        path = root / "materials" / item["path"]
        require(path.is_file() and not path.is_symlink(), "material_file")
        actual = digest(path.read_bytes()); require(actual == item["sha256"], "embedded_material_digest")
        if item["path"].startswith("src/runpod_benchmark/"):
            installed = root / item["path"].removeprefix("src/")
            require(digest(installed.read_bytes()) == actual, "installed_source_digest")
        observed_materials.append({"path": item["path"], "sha256": actual})
    require(digest(pathlib.Path("/usr/local/bin/episode1-entrypoint").read_bytes()) == next(x["sha256"] for x in manifest["materials"] if x["path"] == "runtime/episode1/entrypoint.sh"), "entrypoint_digest")
    require(digest(pathlib.Path("/usr/local/bin/episode1-control").read_bytes()) == next(x["sha256"] for x in manifest["materials"] if x["path"] == "runtime/episode1/control.sh"), "control_digest")
    inventory = []
    for line in command(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n"]).decode().splitlines():
        name, version, arch, status = line.split("\t")
        if status == "installed": inventory.append({"name": name.split(":")[0], "version": version, "architecture": arch})
    for item in manifest["system_packages"]:
        require({k: item[k] for k in ("name", "version", "architecture")} in inventory, "system_package_version")
    dependencies = []
    for runtime in manifest["runtimes"]:
        rt = runtime["runtime"]; python = f"/opt/venvs/{rt}/bin/python"
        require(digest(pathlib.Path(f"/locks/{rt}.lock").read_bytes()) == runtime["lock_sha256"], "installed_lock_digest")
        result = json.loads(command([python, str(root / "runpod_benchmark/dependency_validator.py"), "--runtime", rt, "--lock", f"/locks/{rt}.lock"]))
        require(result["status"] == "pass" and result["lock_sha256"] == runtime["lock_sha256"], "dependency_validation")
        dependencies.append(result)
    verify_control_startup(root)
    report = {"schema_version": "episode1.cpu-smoke.v1", "status": "pass", "manifest_sha256": expected,
              "platform": "linux/amd64", "python_version": platform.python_version(), "materials": observed_materials,
              "system_inventory": sorted(inventory, key=lambda x: (x["name"], x["architecture"])),
              "dependencies": dependencies, "host_keys_present": False, "gpu_validation": "not_run"}
    target = root / "build-evidence/cpu-smoke.json"; target.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f: f.write(canonical(report)); f.flush(); os.fsync(f.fileno())


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--manifest-sha256", required=True)
    collect(p.parse_args().manifest_sha256)
