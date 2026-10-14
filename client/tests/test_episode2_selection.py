from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from token_by_token_cli.errors import ClientError
from token_by_token_cli.selection import capability_digest, select_episode2, write_selection


def capability():
    return {"schema_version":"episode2-capabilities.v1", "episode":2,
            "protocol_sha256":"a"*64,"status":"offline_verified",
            "combinations":[{"mixture_id":"public-fixture-v1","model_id":"loopback-model","gpu_id":"none","mode":"synthetic_mock","limits":{"max_blocks":8,"max_turns_per_block":12}}],
            "proof":{"source_sha256":"b"*64,"material_sha256":"c"*64,"adapter_sha256":"d"*64,"checks_sha256":"e"*64},
            "observed_at":datetime.now(timezone.utc).isoformat(),
            "expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}


def request(c):
    return {"schema_version":"episode2-selection.v1","episode":2,"protocol_sha256":"a"*64,
            "mixture_id":"public-fixture-v1","model_id":"loopback-model","gpu_id":"none",
            "request_id":"f"*32,"capability_sha256":capability_digest(c)}


def test_selection_binds_exact_capability_without_granting_execution():
    c=capability(); r=request(c)
    assert select_episode2(r,c)==r


def test_unavailable_capability_rejects():
    c=capability(); c.update(status="unavailable",combinations=[],proof=None,expires_at=None,observed_at=None)
    with pytest.raises(ClientError): select_episode2(request(c),c)


@pytest.mark.parametrize("field", ["endpoint","profile","env","engine_flags","prompt"])
def test_unbounded_private_request_fields_reject(field):
    c=capability(); r=request(c); r[field]="private-canary"
    with pytest.raises(ClientError): select_episode2(r,c)


@pytest.mark.parametrize("mutation", ["expired","hash","protocol","bool","pair","recorded_offline","proof"])
def test_invalid_selection_rejects(mutation):
    c=capability(); r=request(c)
    if mutation=="expired": c["expires_at"]="2000-01-01T00:00:00+00:00"; r=request(c)
    if mutation=="hash": r["capability_sha256"]="0"*64
    if mutation=="protocol": r["protocol_sha256"]="0"*64
    if mutation=="bool": r["episode"]=True
    if mutation=="pair": r["gpu_id"]="h200-sxm"
    if mutation=="recorded_offline": c["combinations"][0].update(mode="recorded",model_id="qwen2.5-32b-instruct",gpu_id="h200-sxm"); r=request(c)
    if mutation=="proof": c["proof"]["profile"]="private-canary"; r=request(c)
    with pytest.raises(ClientError): select_episode2(r,c)


def test_output_exclusive_and_private(tmp_path):
    c=capability(); r=request(c); p=tmp_path/"selection.json"
    write_selection(p,r,c)
    assert json.loads(p.read_text())==r
    assert p.stat().st_mode & 0o077 == 0
    with pytest.raises(ClientError): write_selection(p,r,c)


def test_output_symlink_ancestor_rejects(tmp_path):
    real=tmp_path/"real"; real.mkdir(); link=tmp_path/"link"; link.symlink_to(real,target_is_directory=True)
    c=capability()
    with pytest.raises(ClientError): write_selection(link/"selection.json",request(c),c)
    assert not list(real.iterdir())

def make_worker(tmp_path, payload):
    p=tmp_path/'worker'; p.write_text('#!/usr/bin/env python3\nprint('+repr(payload)+')\n'); p.chmod(0o700); return p


def test_cli_selection_and_capability(tmp_path,capsys):
    from token_by_token_cli.cli import main
    c=capability(); worker=make_worker(tmp_path,json.dumps(c)); output=tmp_path/'selected.json'
    assert main(['capabilities','--episode','2','--worker',str(worker),'--format','json'])==0
    assert json.loads(capsys.readouterr().out)==c
    assert main(['episode','2','select','--worker',str(worker),'--mixture','public-fixture-v1','--model','loopback-model','--gpu','none','--output',str(output),'--format','json'])==0
    selected=json.loads(capsys.readouterr().out)
    assert selected==json.loads(output.read_text())


@pytest.mark.parametrize('payload',[ '{"episode":2,"episode":2}', '{"x":NaN}', '[]' ])
def test_worker_invalid_json_rejected(tmp_path,payload):
    from token_by_token_cli.selection import read_episode2_capability
    with pytest.raises(ClientError): read_episode2_capability(make_worker(tmp_path,payload))

@pytest.mark.parametrize('payload',['{"x":1,"x":2}','{"x":NaN}'])
def test_transport_rejects_duplicate_and_nonfinite_before_validation(tmp_path,payload):
    from token_by_token_cli.local_worker import _invoke
    with pytest.raises(ClientError): _invoke(make_worker(tmp_path,payload),['capabilities','--json'])


def test_provider_capability_cannot_be_indefinitely_fresh():
    c=capability();c['status']='provider_verified';c['combinations'][0].update(mode='recorded',model_id='qwen2.5-32b-instruct',gpu_id='h200-sxm')
    c['expires_at']='9999-12-31T23:59:59+00:00'
    with pytest.raises(ClientError):select_episode2(request(c)|{'model_id':'qwen2.5-32b-instruct','gpu_id':'h200-sxm'},c)


def test_fixed_mixture_cannot_advertise_impossible_turn_limit():
    c=capability();c['combinations'][0]['limits']['max_turns_per_block']=1
    with pytest.raises(ClientError):select_episode2(request(c),c)
