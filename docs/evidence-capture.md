# Evidence capture and redaction

Keep raw evidence in a mode-`0700` directory outside the repository. The public
bundle contains aggregates only.

## GPU and runtime capture

`scripts/capture_gpu_telemetry.py` queries timestamp, GPU index/name,
utilization, memory, power, and temperature. It intentionally omits GPU UUID,
serial number, host name, IP address, and process command lines. Pair its CSV
with exact UTC start/end timestamps and runtime-native JSONL.

For a human-readable hardware screenshot, use:

```bash
nvidia-smi --query-gpu=timestamp,index,name,memory.total,driver_version \
  --format=csv,noheader,nounits
```

Before sharing, redact terminal user/host, Pod ID, GPU UUID/serial, network
address, access URL, shell history, tokens, and unrelated processes. Preserve
the timestamp, GPU model, VRAM, driver version, and command.

## Runpod billing capture

Take one screenshot immediately before creation and another after verified
deletion and billing settlement. Select the exact resource date range. Preserve
timestamps, line-item category, unit price, duration, and total. Redact account
identity, payment method, Pod/volume/endpoint IDs, IPs, SSH commands, access
URLs, and unrelated resources. Store originals privately and publish only
reviewed redacted copies.

The historical Episode 0 package has no retained Runpod or NIM screenshots.
Never manufacture or relabel a new screenshot as historical evidence.

## Public evidence rule

Aggregate only after checking attempts, successes/failures, cell boundaries,
output-length distributions, stop reasons, and sampling windows. Hash every
public file. The verifier establishes package integrity and consistency, not
experimental validity.
