ARG BASE_IMAGE=vllm/vllm-openai:v0.29.0
FROM ${BASE_IMAGE}

WORKDIR /opt/inference-lab
COPY pyproject.toml /opt/inference-lab/pyproject.toml
COPY scripts /opt/inference-lab/scripts
COPY src /opt/inference-lab/src

# The upstream image starts an API server. The operator image must idle until
# the digest-bound launch command has been checked on the allocated GPU.
ENTRYPOINT []
CMD ["sleep", "infinity"]
