FROM --platform=linux/amd64 nvidia/cuda@sha256:a85c9f5af049f0ab679c1669ae6fa8393022886739af7361e85bb96878e8cdd4
ENV PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/episode2/src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN --network=none --mount=type=bind,from=system,target=/system,ro \
    printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
 && chmod 0755 /usr/sbin/policy-rc.d \
 && cd /system && sha256sum --check --strict debs.sha256 \
 && DEBIAN_FRONTEND=noninteractive dpkg -i /system/debs/*.deb \
 && rm -f /etc/ssh/ssh_host_*
COPY --from=venvs . /opt/venvs
COPY --from=models model-*.safetensors /opt/models/qwen2.5-32b-instruct/
COPY --from=models config.json generation_config.json merges.txt model.safetensors.index.json tokenizer.json tokenizer_config.json vocab.json /opt/models/qwen2.5-32b-instruct/
COPY payload /opt/episode2
RUN --network=none install -m 0755 /opt/episode2/runtime/entrypoint.sh /usr/local/bin/episode2-entrypoint \
 && install -m 0755 /opt/episode2/runtime/control.sh /usr/local/bin/episode2-control \
 && /opt/venvs/vllm/bin/python /opt/episode2/src/runpod_benchmark/dependency_validator.py --runtime vllm --lock /opt/episode2/locks/vllm.lock > /opt/episode2/build-evidence/vllm-image-dependencies.json \
 && /opt/venvs/sglang/bin/python /opt/episode2/src/runpod_benchmark/dependency_validator.py --runtime sglang --lock /opt/episode2/locks/sglang.lock > /opt/episode2/build-evidence/sglang-image-dependencies.json \
 && /opt/venvs/vllm/bin/python /opt/episode2/runtime/cpu_probe.py vllm > /opt/episode2/build-evidence/vllm-image-cpu.json \
 && /opt/venvs/sglang/bin/python /opt/episode2/runtime/cpu_probe.py sglang > /opt/episode2/build-evidence/sglang-image-cpu.json \
 && /usr/local/bin/episode2-control --help > /opt/episode2/build-evidence/control-help.txt \
 && /usr/bin/python3.12 -c 'import runpod_benchmark.episode2_runner,runpod_benchmark.episode2_analysis; print("public_harness_import_pass")' > /opt/episode2/build-evidence/harness-import.txt \
 && test ! -e /etc/ssh/ssh_host_ed25519_key
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/episode2-entrypoint"]
