"""Observe the actual native vLLM config once, then run its unchanged launcher."""
from __future__ import annotations
import functools
import json
import os
import re
import runpy
import sys
import time


def configuration_observation(config,execution_sha256,epoch_id):
    scheduler=config.scheduler_config;cache=config.cache_config
    values={name:getattr(scheduler,name) for name in ('max_num_batched_tokens','max_num_seqs','enable_chunked_prefill','async_scheduling','scheduler_cls')}
    values['scheduling_policy']=scheduler.policy
    values.update({name:getattr(cache,name) for name in ('enable_prefix_caching','gpu_memory_utilization','num_gpu_blocks','block_size')})
    if isinstance(values['scheduler_cls'],type):
        cls=values['scheduler_cls']; values['scheduler_cls']=cls.__module__+'.'+cls.__qualname__
    return {'schema_version':'episode2.native-effective-config.v1','engine':'vllm',
            'execution_sha256':execution_sha256,'epoch_id':epoch_id,'observed_monotonic_ns':time.monotonic_ns(),
            'stage':'actual_returned_engine_config','config':values}


def main():
    engine=sys.argv[1] if len(sys.argv)>1 else None
    if engine not in {'vllm','sglang'}:raise ValueError('engine_required')
    execution=os.environ.get('EPISODE2_EXECUTION_SHA256','');epoch=os.environ.get('EPISODE2_EPOCH_ID','')
    if not re.fullmatch('[0-9a-f]{64}',execution) or not re.fullmatch('epoch-[A-Za-z0-9_-]{1,64}',epoch):
        raise ValueError('launcher_authority_missing')
    if engine=='vllm':
        from vllm.engine.arg_utils import EngineArgs
        original=EngineArgs.create_engine_config
        @functools.wraps(original)
        def observe(self,*args,**kwargs):
            config=original(self,*args,**kwargs)
            print(json.dumps(configuration_observation(config,execution,epoch),sort_keys=True,separators=(',',':'),allow_nan=False),flush=True)
            return config
        EngineArgs.create_engine_config=observe
    module='vllm.entrypoints.openai.api_server' if engine=='vllm' else 'sglang.launch_server'
    sys.argv=[module]+sys.argv[2:]
    runpy.run_module(module,run_name='__main__')


if __name__=='__main__':main()
