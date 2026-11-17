"""Hash-pinned offline tokenizer admission for purpose-written Episode 02 inputs."""
from __future__ import annotations
import hashlib
from pathlib import Path
from runpod_benchmark.episode2_contract import document_digest,require
from runpod_benchmark.episode2_corpus import TOOL_FIXTURES,build_trace,expected_messages
from build_episode1_prompts import ASSET_HASHES,EXPECTED_CHAT_TEMPLATE_SHA256


def build(tokenizer_directory: Path,protocol: dict) -> dict:
    try:
        hashes={name:hashlib.sha256((tokenizer_directory/name).read_bytes()).hexdigest() for name in ASSET_HASHES}
    except OSError as exc:
        raise ValueError('missing pinned tokenizer assets') from exc
    require(hashes==ASSET_HASHES,'tokenizer asset hashes mismatch')
    from transformers import AutoTokenizer
    import transformers,tokenizers
    tokenizer=AutoTokenizer.from_pretrained(tokenizer_directory,local_files_only=True,trust_remote_code=False)
    require(hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()==EXPECTED_CHAT_TEMPLATE_SHA256,'chat template hash mismatch')
    trace=build_trace(protocol);rows=[]
    for turn in trace['blocks'][0]['turns']:
        messages=expected_messages(turn)
        tool_turn=(turn['class_id']=='tool_call' and turn['turn_id']=='turn-1') or (turn['class_id']=='agent_chain' and turn['turn_id']=='turn-2')
        tools=[{'type':'function','function':{'name':'lookup_inventory','parameters':TOOL_FIXTURES['lookup_inventory']['schema']}}] if tool_turn else None
        ids=tokenizer.apply_chat_template(messages,tools=tools,tokenize=True,add_generation_prompt=True)
        if hasattr(ids,'input_ids'):ids=ids.input_ids
        if ids and isinstance(ids[0],list):ids=ids[0]
        require(isinstance(ids,list) and ids and all(type(i) is int and i>=0 for i in ids),'exact token IDs required')
        spec=protocol['mixture']['classes'][turn['class_id']]
        admitted=spec['input_tokens_min']<=len(ids)<=spec['input_tokens_max']
        require(admitted,f"input band mismatch for {turn['class_id']} {turn['turn_id']}: {len(ids)} tokens")
        require(len(ids)+spec['requested_output_tokens']<=protocol['material']['context_window'],'rendered context overflow')
        rows.append({'logical_request_id':turn['logical_request_id'],'class_id':turn['class_id'],'turn_id':turn['turn_id'],'messages_sha256':document_digest(messages),'tools_sha256':document_digest(tools),'input_tokens':len(ids),'input_token_ids_sha256':document_digest(ids),'requested_output_tokens':spec['requested_output_tokens'],'admitted':admitted})
    return {'schema_version':'episode2.tokenizer-admission.v1','classification':'purpose_written_input','model_candidate':'Qwen/Qwen2.5-32B-Instruct','model_revision':'5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd','protocol_sha256':document_digest(protocol),'trace_sha256':document_digest(trace),'asset_sha256':hashes,'template_sha256':EXPECTED_CHAT_TEMPLATE_SHA256,'tool_versions':{'transformers':transformers.__version__,'tokenizers':tokenizers.__version__},'turns':rows}
