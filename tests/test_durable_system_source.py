from __future__ import annotations
import gc
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark import episode1_capture as capture_module
from runpod_benchmark.episode1_capture import (
    EvidenceCaptureV2, IntegrityError, RunContract, load_retained_system_sources,
)
from runpod_benchmark.episode1_telemetry import Episode1BlockTelemetry, TelemetrySeriesSpec

PLAN_SHA='a'*64
BLOCKS=tuple((f'block-{i}', 'vllm' if i%2 else 'sglang') for i in range(1,7))

def contract():
    counts={}
    for block,_runtime in BLOCKS:
        counts[f'{block}|cell|1']=12
        counts[f'{block}|cell|0']=88
    return RunContract('run-1','attempt-1',PLAN_SHA,'b'*64,'c'*64,BLOCKS,counts,('sys',),
        10,20,1_000_000,900_000,'clock','boot')

class Clock:
    def __init__(self): self.n=10
    def mono(self): self.n+=1; return self.n
    def utc(self): return 1_000+self.n

def capture_at(parent: Path):
    c=Clock(); con=contract()
    cap=EvidenceCaptureV2(parent/'evidence',con,monotonic_ns=c.mono,utc_ns=c.utc,
        observation_validator=lambda value:value)
    return cap,con

class FailingNative:
    def abort(self, **kwargs): raise TimeoutError('injected native abort failure')

class DurableSystemSourceTests(unittest.TestCase):
    def make_block(self, cap):
        return Episode1BlockTelemetry(plan={'plan_sha256':PLAN_SHA},
            block={'block_id':'block-1','runtime':'vllm'}, run_attempt_id='attempt-1',
            startup_attempt_id='block-1-attempt-1', block_attempt=1,
            allocation=SimpleNamespace(unique_name='run-1'), capture=cap,
            specs=[TelemetrySeriesSpec('sys','system_source_window','gpu','gauge',{})],
            native=FailingNative(), max_system_sampling_gap_ns=1, native_clock_domain='clock')

    @staticmethod
    def sample(record=None):
        record=({'sequence':1,'phase':'startup',
                 'binding':{'run_id':'run-1','attempt_id':'attempt-1','block':'block-1'}}
                if record is None else record)
        encoded=(canonical_json(record)+'\n').encode()
        return {'record':record,'source_sha256':hashlib.sha256(encoded).hexdigest()},encoded

    def test_successful_sample_is_durable_and_normal_source_bytes_unchanged(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); block=self.make_block(cap); value,encoded=self.sample()
            block.system_sample(value)
            self.assertEqual(bytes(block._system),encoded)
            reopened=load_retained_system_sources(cap.directory,con)
            self.assertEqual(len(reopened),1)
            self.assertEqual(reopened[0]['record'],value['record'])
            self.assertEqual(reopened[0]['source_sha256'],value['source_sha256'])

    def test_failed_native_abort_leaves_reopenable_record_after_object_discard(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); block=self.make_block(cap); value,_=self.sample()
            block.system_sample(value)
            with self.assertRaises(TimeoutError): block.abort(deadline_monotonic=1.0)
            directory=cap.directory
            del block; gc.collect()
            self.assertEqual([x['record'] for x in load_retained_system_sources(directory,con)],
                             [value['record']])
            self.assertEqual((directory/'telemetry.jsonl').read_bytes(),b'')

    def test_append_failure_fails_closed_before_memory_acceptance(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,_=capture_at(Path(td)); block=self.make_block(cap); value,_=self.sample()
            with patch('runpod_benchmark.episode1_capture._append',side_effect=OSError('disk')):
                with self.assertRaises(OSError): block.system_sample(value)
            self.assertEqual(bytes(block._system),b'')
            self.assertEqual((cap.directory/'system-source.jsonl').read_bytes(),b'')

    def test_binding_hash_and_bound_rejections_leave_stream_empty(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); value,encoded=self.sample()
            payload={'schema_version':'episode1.system-source-evidence.v1',
                'plan_sha256':PLAN_SHA,'block_id':'block-1','runtime':'vllm',
                'run_attempt_id':'attempt-1','startup_attempt_id':'block-1-attempt-1',
                'block_attempt':1,'source_sha256':value['source_sha256'],
                'record':value['record']}
            for changed in ({**payload,'block_id':'block-X'},
                            {**payload,'run_attempt_id':'attempt-X'},
                            {**payload,'startup_attempt_id':'block-1-attempt-2'},
                            {**payload,'block_attempt':2},
                            {**payload,'source_sha256':'0'*64}):
                with self.assertRaises((ValueError,IntegrityError)): cap.system_source(changed)
            with patch('runpod_benchmark.episode1_capture.MAX_SYSTEM_SOURCE_BYTES_PER_BLOCK',
                       len(encoded)-1):
                with self.assertRaisesRegex(ValueError,'retention bound'): cap.system_source(payload)
            with patch('runpod_benchmark.episode1_capture.MAX_SYSTEM_SOURCE_RECORDS',0):
                with self.assertRaisesRegex(ValueError,'record bound'): cap.system_source(payload)
            self.assertEqual(load_retained_system_sources(cap.directory,con),[])

    def test_reopen_enforces_stream_file_bound_before_read(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td))
            path=cap.directory/'system-source.jsonl'
            path.write_bytes(b'x')
            with patch('runpod_benchmark.episode1_capture.MAX_SYSTEM_SOURCE_STREAM_BYTES',0):
                with self.assertRaisesRegex(IntegrityError,'exceeds its bound'):
                    load_retained_system_sources(cap.directory,con)

    def test_bounded_reader_does_not_call_unbounded_stream_reader(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); block=self.make_block(cap); value,_=self.sample()
            block.system_sample(value)
            with patch.object(capture_module, '_read_stream',
                              side_effect=AssertionError('unbounded reader used')):
                reopened,head=capture_module._read_bounded_system_source_stream(cap.directory,con)
            self.assertEqual(len(reopened),1)
            self.assertEqual(head,cap._stream['system-source'][1])

    def test_bounded_reader_rejects_symlink_and_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            root=Path(td); cap,con=capture_at(root)
            original=cap.directory/'system-source.jsonl'
            target=root/'target'; target.write_bytes(original.read_bytes())
            original.unlink(); original.symlink_to(target)
            with self.assertRaises(IntegrityError): load_retained_system_sources(cap.directory,con)
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); path=cap.directory/'system-source.jsonl'
            path.unlink(); os.mkfifo(path,mode=0o600)
            with self.assertRaises(IntegrityError): load_retained_system_sources(cap.directory,con)

    def test_bounded_reader_rejects_changed_open_file_identity(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); block=self.make_block(cap); value,_=self.sample()
            block.system_sample(value)
            actual=os.stat(cap.directory/'system-source.jsonl')
            changed=SimpleNamespace(st_dev=actual.st_dev,st_ino=actual.st_ino,
                st_mode=actual.st_mode,st_nlink=actual.st_nlink,st_size=actual.st_size,
                st_mtime_ns=actual.st_mtime_ns+1,st_ctime_ns=actual.st_ctime_ns)
            with patch.object(capture_module.os,'fstat',side_effect=[actual,changed]):
                with self.assertRaisesRegex(IntegrityError,'changed while'):
                    load_retained_system_sources(cap.directory,con)

    def test_reopen_detects_payload_tampering(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); block=self.make_block(cap); value,_=self.sample()
            block.system_sample(value)
            path=cap.directory/'system-source.jsonl'
            entry=json.loads(path.read_text())
            entry['payload']['record']['sequence']=2
            path.write_text(json.dumps(entry,separators=(',',':'))+'\n')
            with self.assertRaises(IntegrityError): load_retained_system_sources(cap.directory,con)

    def test_reopen_rejects_boolean_block_attempt_as_integrity_failure(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as td:
            cap,con=capture_at(Path(td)); value,_=self.sample()
            payload={'schema_version':'episode1.system-source-evidence.v1',
                'plan_sha256':PLAN_SHA,'block_id':'block-1','runtime':'vllm',
                'run_attempt_id':'attempt-1','startup_attempt_id':'block-1-attempt-1',
                'block_attempt':True,'source_sha256':value['source_sha256'],
                'record':value['record']}
            with patch.object(capture_module, '_parse_stream', return_value=([payload], '0'*64)):
                with self.assertRaisesRegex(IntegrityError,'block attempt'):
                    load_retained_system_sources(cap.directory,con)

if __name__=='__main__': unittest.main()
