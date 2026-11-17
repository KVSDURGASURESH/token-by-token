import hashlib, json, subprocess, sys
engine=sys.argv[1]
modules={'vllm':['torch','vllm','vllm.entrypoints.openai.api_server'], 'sglang':['torch','sglang','sglang.launch_server']}[engine]
results=[]
for name in modules:
    try:
        r=subprocess.run([sys.executable,'-c',f'import {name}'],capture_output=True,timeout=180)
        results.append({'module':name,'returncode':r.returncode,'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest(),'stderr_tail':r.stderr.decode(errors='replace')[-5000:]})
    except subprocess.TimeoutExpired:
        results.append({'module':name,'status':'timeout','timeout_seconds':180})
try:
    r=subprocess.run([sys.executable,'-c','import torch,json; print(json.dumps({"torch":torch.__version__,"cuda":torch.version.cuda,"gpu_available":torch.cuda.is_available(),"compiled_arch_flags":torch._C._cuda_getArchFlags()}))'],capture_output=True,timeout=180)
    arch={'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')[-3000:]}
except subprocess.TimeoutExpired:
    arch={'status':'timeout'}
print(json.dumps({'schema_version':'episode2.cpu-probe.v1','engine':engine,'gpu_verification':'unverified','imports':results,'architecture_probe':arch},indent=2))
