from __future__ import annotations

import argparse
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def safe_path(root: Path, name: str) -> Path:
    cleaned = name.replace("\\", "/").strip("/")
    parts = [part for part in cleaned.split("/") if part not in {"", ".", ".."}]
    if not parts:
        parts = ["unnamed"]
    return root.joinpath(*parts)


def extract_archive(binary: Path, output: Path) -> None:
    reader = CArchiveReader(str(binary))
    output.mkdir(parents=True, exist_ok=False)
    for index, name in enumerate(reader.toc):
        payload = reader.extract(name)
        if payload is None:
            continue
        target = safe_path(output, f"{index:04d}-{name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        try:
            embedded = reader.open_embedded_archive(name)
        except Exception:
            if name.lower().endswith(".pyz"):
                raise
            continue
        nested = output / f"{index:04d}-{name}.contents"
        nested.mkdir(parents=True, exist_ok=True)
        for nested_index, nested_name in enumerate(embedded.toc):
            try:
                nested_payload = embedded.extract(nested_name, raw=True)
            except TypeError:
                nested_payload = embedded.extract(nested_name)
            if isinstance(nested_payload, bytes):
                nested_target = safe_path(nested, f"{nested_index:04d}-{nested_name}")
                nested_target.parent.mkdir(parents=True, exist_ok=True)
                nested_target.write_bytes(nested_payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract_archive(args.binary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
