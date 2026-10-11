from pathlib import Path
import json

from PyInstaller.utils.hooks import collect_data_files


root = Path(SPECPATH)
public_resources = collect_data_files("token_by_token_cli", includes=["resources/**/*.json"])
a = Analysis(
    [str(root / "run_client.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=public_resources,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["runpod_benchmark"],
    noarchive=False,
    optimize=0,
)

inventory = {
    "modules": sorted({entry[0] for entry in [*a.pure, *a.scripts]}),
    "resources": sorted({entry[0] for entry in [*a.datas, *a.binaries]}),
}
(root / "build").mkdir(exist_ok=True)
(root / "build" / "analysis-inventory.json").write_text(
    json.dumps(inventory, sort_keys=True, separators=(",", ":")), encoding="utf-8"
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="token-by-token",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
