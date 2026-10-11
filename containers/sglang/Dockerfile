ARG BASE_IMAGE=lmsysorg/sglang:v0.5.20
FROM ${BASE_IMAGE}

WORKDIR /opt/inference-lab
COPY pyproject.toml /opt/inference-lab/pyproject.toml
COPY scripts /opt/inference-lab/scripts
COPY src /opt/inference-lab/src

# Clear upstream launch behavior so the reviewed runtime command is explicit.
ENTRYPOINT []
CMD ["sleep", "infinity"]
