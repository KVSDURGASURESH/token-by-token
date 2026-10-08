from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def clean_build_environment(temporary_root: Path, executable_dir: Path) -> dict[str, str]:
    return {
        "PATH": os.pathsep.join((str(executable_dir), os.defpath)),
        "HOME": str(temporary_root / "home"),
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": "1767225600",
        "TMPDIR": str(temporary_root / "tmp"),
    }


def load_auditor(root: Path):
    sys.path.insert(0, str(root.parent))
    sys.path.insert(0, str(root / "src"))
    from client.scripts.audit_binary import audit_binary

    return audit_binary


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if Path.cwd().resolve() != root:
        raise SystemExit("build_binary.py must run from client/")
    build = root / "build"
    dist = root / "dist"
    for target in (build, dist):
        if target.exists():
            shutil.rmtree(target)
    with tempfile.TemporaryDirectory(prefix="token-by-token-build-") as temporary:
        environment = Path(temporary) / "venv"
        run([sys.executable, "-m", "venv", str(environment)], cwd=root)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-m", "pip", "install", "--require-hashes", "-r", str(root / "requirements-build.lock")], cwd=root)
        run([str(python), "-m", "pip", "install", "--no-deps", "."], cwd=root)
        clean_env = clean_build_environment(Path(temporary), python.parent)
        Path(clean_env["HOME"]).mkdir()
        Path(clean_env["TMPDIR"]).mkdir()
        run([str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "token-by-token.spec"], cwd=root, env=clean_env)
        binary = dist / ("token-by-token.exe" if os.name == "nt" else "token-by-token")
        extracted = Path(temporary) / "extracted"
        run([str(python), str(root / "scripts" / "extract_binary.py"), str(binary), str(extracted)], cwd=root, env=clean_env)
        audit_binary = load_auditor(root)
        audit_binary(binary, build / "analysis-inventory.json", extracted)
        run([str(binary), "--version"], cwd=root, env=clean_env)
        smoke = Path(temporary) / "smoke.tbt.zip"
        run([str(binary), "episode", "2", "selftest", "--offline", "--users", "4", "--output", str(smoke)], cwd=root, env=clean_env)
        run([str(binary), "evidence", "verify", str(smoke)], cwd=root, env=clean_env)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(f"{digest}  {binary.name}\n", encoding="utf-8")
    print(f"candidate: {binary}")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
