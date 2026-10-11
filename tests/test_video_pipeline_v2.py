import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
definition=importlib.util.spec_from_file_location('tbt_video_pipeline',ROOT/'skills/token-by-token-video/scripts/pipeline.py')
pipeline=importlib.util.module_from_spec(definition);definition.loader.exec_module(pipeline)

class VideoInputInvariants(unittest.TestCase):
    def setUp(self): self.spec=json.loads((ROOT/'video/specs/episode-01.v2.json').read_text())
    def test_public_claims_and_timeline_are_valid(self): self.assertTrue(pipeline.validate(self.spec))
    def test_changed_public_measurement_is_rejected(self):
        self.spec['claims'][2]['value']+=1
        with self.assertRaisesRegex(AssertionError,'stale claim'): pipeline.validate(self.spec)
    def test_timeline_gap_is_rejected(self):
        self.spec['scenes'][2]['start']+=.5
        with self.assertRaisesRegex(AssertionError,'timeline'): pipeline.validate(self.spec)
    def test_lookalike_qr_host_is_rejected(self):
        self.spec['qr_url']='https://tokenbytoken.org.example.com'
        with self.assertRaisesRegex(AssertionError,'owner portal'): pipeline.validate(self.spec)
    def test_upward_capture_is_rejected(self):
        self.spec['captures'][0]['travel']=-1
        with self.assertRaisesRegex(AssertionError,'capture'): pipeline.validate(self.spec)

if __name__=='__main__': unittest.main()
