import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json

CANDIDATE = Path(__file__).resolve().parents[1]
compiler_spec = importlib.util.spec_from_file_location(
    'compile_episode1_execution', CANDIDATE / 'scripts/compile_episode1_execution.py'
)
c = importlib.util.module_from_spec(compiler_spec)
compiler_spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location('execution_fixtures', CANDIDATE/'tests/test_episode1_execution.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.data.mkdir(mode=0o700)
        (self.data/'model.txt').write_bytes(b'frozen material\n')
        entries = [{'path':'data/model.txt','sha256':hashlib.sha256(b'frozen material\n').hexdigest()}]
        self.manifest = {'classification':'execution_material_hashes','files':entries,
                         'aggregate_sha256':hashlib.sha256(canonical_json(entries).encode()).hexdigest()}
        self.inputs = f.inputs(ready=False)
        self.inputs['material_sha256'] = self.manifest['aggregate_sha256']
        self.protocol = self.root/'protocol.json'; self.protocol.write_text(canonical_json(f.protocol()))
        self.material = self.root/'material.json'; self.material.write_text(canonical_json(self.manifest))
        self.input_file = self.root/'inputs.json'
        self.save_inputs()
    def save_inputs(self): self.input_file.write_text(canonical_json(self.inputs))
    def compile(self, **kwargs):
        return c.compile_files(protocol_path=self.protocol, inputs_path=self.input_file,
                               material_path=self.material, repository_root=self.root,
                               head_reader=lambda _: 'c'*40, **kwargs)
    def test_actual_material_bound_blocked_candidate(self):
        result=self.compile()
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['material_sha256'],self.manifest['aggregate_sha256'])
        self.assertEqual(len(result['blocks']),6)
    def test_changed_material_rejected(self):
        (self.data/'model.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.compile()
    def test_wrong_head_rejected(self):
        self.inputs['source_commit']='d'*40; self.save_inputs()
        with self.assertRaises(ValueError): self.compile()
    def test_strict_json_duplicate_and_nonfinite_rejected(self):
        for raw in (b'{"files":[],"files":[]}',b'{"files":NaN}'):
            with self.subTest(raw=raw):
                self.material.write_bytes(raw)
                with self.assertRaises(ValueError): self.compile()
    def test_material_parent_and_file_symlinks_rejected(self):
        original=self.data/'model.txt'; original.rename(self.data/'other.txt')
        original.symlink_to('other.txt')
        with self.assertRaises(OSError): self.compile()
        original.unlink(); (self.data/'other.txt').rename(original)
        self.data.rename(self.root/'elsewhere'); self.data.symlink_to('elsewhere')
        with self.assertRaises(OSError): self.compile()
    def test_fifo_rejected_without_wait(self):
        target=self.data/'model.txt'; target.unlink(); os.mkfifo(target)
        with self.assertRaises(ValueError): self.compile()
    def test_size_and_file_count_bounds(self):
        with patch.object(c,'MAX_FILE',3):
            with self.assertRaises(ValueError): self.compile()
        with patch.object(c,'MAX_FILES',0):
            with self.assertRaises(ValueError): self.compile()
    def test_path_traversal_rejected(self):
        self.manifest['files'][0]['path']='../outside'
        self.material.write_text(canonical_json(self.manifest))
        with self.assertRaises(ValueError): self.compile()
    def test_ready_compile_requires_current_quote(self):
        self.inputs=f.inputs(); self.inputs['material_sha256']=self.manifest['aggregate_sha256']; self.save_inputs()
        current=datetime(2026,9,22,12,1,tzinfo=timezone.utc)
        self.assertTrue(self.compile(now=current)['execution_ready'])
        with self.assertRaises(ValueError): self.compile(now=datetime(2026,9,22,12,16,tzinfo=timezone.utc))
    def test_output_private_complete_and_no_overwrite(self):
        p=self.root/'out.json'; c.write_private_exclusive(p,b'complete\n')
        self.assertEqual(p.read_bytes(),b'complete\n'); self.assertEqual(p.stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError): c.write_private_exclusive(p,b'overwrite')
        self.assertEqual(p.read_bytes(),b'complete\n')
        self.assertEqual(list(self.root.glob('.episode1-compile-*')),[])
    def test_output_nonprivate_or_symlink_parent_rejected(self):
        self.data.chmod(0o755)
        with self.assertRaises(ValueError): c.write_private_exclusive(self.data/'out',b'x')
        link=self.root/'link'; link.symlink_to(self.data)
        with self.assertRaises(ValueError): c.write_private_exclusive(link/'out',b'x')
    def test_cli_real_head_and_material_smoke(self):
        # Exercise the real Git reader without depending on the source checkout's
        # worktree metadata or tracked contents.
        repository=self.root/'repository'; repository.mkdir(mode=0o700)
        relative='material.txt'; payload=b'frozen cli material\n'
        (repository/relative).write_bytes(payload)
        git_home=self.root/'git-home'; git_home.mkdir(mode=0o700)
        git_env={key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
        git_env.update({'HOME':str(git_home),'LC_ALL':'C','GIT_CONFIG_GLOBAL':os.devnull,
                        'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'})
        def git(*arguments):
            return subprocess.run(['/usr/bin/git','-C',str(repository),*arguments],check=True,
                                  stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                  timeout=5,env=git_env)
        git('init','-q')
        git('config','user.email','fixture@example.invalid')
        git('config','user.name','Episode1 test fixture')
        git('add','--',relative)
        git('commit','-qm','fixture','--no-gpg-sign')
        entries=[{'path':relative,'sha256':hashlib.sha256(payload).hexdigest()}]
        manifest={'classification':'execution_material_hashes','files':entries,
                  'aggregate_sha256':hashlib.sha256(canonical_json(entries).encode()).hexdigest()}
        self.material.write_text(canonical_json(manifest)); self.inputs['material_sha256']=manifest['aggregate_sha256']
        self.inputs['source_commit']=c.observed_head(repository); self.save_inputs()
        args=[sys.executable,str(Path(c.__file__)), '--protocol',str(self.protocol), '--inputs',str(self.input_file),
              '--material',str(self.material),'--repository-root',str(repository),'--output',str(self.root/'candidate.json')]
        result=subprocess.run(args,check=True,capture_output=True,text=True,timeout=10)
        summary=json.loads(result.stdout)
        self.assertFalse(summary['execution_ready'])
        self.assertNotIn('APPROVE',result.stdout)
        self.assertEqual(set(summary),{'plan_sha256','plan_file_sha256','execution_ready','unresolved_blocker_count'})
        self.assertEqual(json.loads((self.root/'candidate.json').read_text())['plan_sha256'],summary['plan_sha256'])

if __name__=='__main__': unittest.main()
