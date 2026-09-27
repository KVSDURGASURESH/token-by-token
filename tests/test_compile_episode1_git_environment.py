import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json

CANDIDATE = Path(__file__).resolve().parents[1]
compiler_spec = importlib.util.spec_from_file_location(
    'compile_episode1_execution', CANDIDATE / 'scripts/compile_episode1_execution.py'
)
c = importlib.util.module_from_spec(compiler_spec)
compiler_spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location(
    'execution_fixtures', CANDIDATE / 'tests/test_episode1_execution.py'
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class AmbientGitEnvironmentTests(unittest.TestCase):
    def _repo(self, path: Path, content: bytes) -> str:
        path.mkdir()
        subprocess.run(['/usr/bin/git', '-C', str(path), 'init', '-q'], check=True)
        subprocess.run(['/usr/bin/git', '-C', str(path), 'config', 'user.email', 'fixture@example.invalid'], check=True)
        subprocess.run(['/usr/bin/git', '-C', str(path), 'config', 'user.name', 'fixture'], check=True)
        (path / 'material.bin').write_bytes(content)
        subprocess.run(['/usr/bin/git', '-C', str(path), 'add', 'material.bin'], check=True)
        subprocess.run(['/usr/bin/git', '-C', str(path), 'commit', '-qm', 'fixture'], check=True)
        return subprocess.run(
            ['/usr/bin/git', '-C', str(path), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_compile_rejects_foreign_head_from_ambient_git_environment(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, foreign = base / 'target', base / 'foreign'
            target_head = self._repo(target, b'target material')
            foreign_head = self._repo(foreign, b'foreign material')
            self.assertNotEqual(target_head, foreign_head)

            entries = [{
                'path': 'material.bin',
                'sha256': hashlib.sha256(b'target material').hexdigest(),
            }]
            manifest = {
                'classification': 'execution_material_hashes',
                'files': entries,
                'aggregate_sha256': hashlib.sha256(canonical_json(entries).encode()).hexdigest(),
            }
            inputs = fixtures.inputs(ready=False)
            inputs['material_sha256'] = manifest['aggregate_sha256']
            inputs['source_commit'] = foreign_head
            protocol_path = base / 'protocol.json'
            inputs_path = base / 'inputs.json'
            material_path = base / 'manifest.json'
            protocol_path.write_text(canonical_json(fixtures.protocol()))
            inputs_path.write_text(canonical_json(inputs))
            material_path.write_text(canonical_json(manifest))

            with patch.dict(os.environ, {'GIT_DIR': str(foreign / '.git'),
                                         'GIT_WORK_TREE': str(foreign),
                                         'GIT_CONFIG_COUNT': '1',
                                         'GIT_CONFIG_KEY_0': 'core.worktree',
                                         'GIT_CONFIG_VALUE_0': str(foreign)}):
                with self.assertRaises(ValueError):
                    c.compile_files(
                    protocol_path=protocol_path,
                    inputs_path=inputs_path,
                    material_path=material_path,
                    repository_root=target,
                )
                self.assertEqual(c.observed_head(target), target_head)


if __name__ == '__main__':
    unittest.main()
