import os
from pathlib import Path
import pytest
from runpod_benchmark.episode2_corpus import make_synthetic_protocol
from build_episode2_inputs import build


def test_missing_or_changed_tokenizer_assets_fail_closed(tmp_path):
    with pytest.raises(ValueError,match='asset'):
        build(tmp_path,make_synthetic_protocol())


@pytest.mark.skipif(not os.environ.get('TBT_EPISODE2_TOKENIZER_DIR'),reason='explicit pinned offline tokenizer assets not supplied')
def test_real_pinned_tokenizer_admits_every_initial_and_dependent_turn():
    result=build(Path(os.environ['TBT_EPISODE2_TOKENIZER_DIR']),make_synthetic_protocol())
    assert result['classification']=='purpose_written_input'
    assert len(result['turns'])==12
    assert all(row['admitted'] for row in result['turns'])
    assert len({row['logical_request_id'] for row in result['turns']})==12
    long=next(row for row in result['turns'] if row['class_id']=='long_prefill')
    assert 2048<=long['input_tokens']<=4096
    assert all(row['input_token_ids_sha256'] and row['messages_sha256'] for row in result['turns'])
