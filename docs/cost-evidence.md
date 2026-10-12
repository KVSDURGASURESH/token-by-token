# Episode 0 — cost evidence

Amounts below reconcile the retained study record with a read-only RunPod billing API query made on 2026-10-10. Daily billing buckets are observed provider data; phase-level figures are explicitly labeled estimates. No new paid experiment was run for this publication.

| Activity | Amount (USD) | Evidence and interpretation |
|---|---:|---|
| September 19–20 Episode 00 campaign | **11.8311 total** | [RunPod billing summary](../data/public/runpod-billing-summary.json): 11.6870 GPU + 0.1441 disk. Includes the earlier RTX PRO 6000 trial and the H100/A100 campaign day. |
| Offline fixture rehearsal / local dashboard | **0 provider charge** | Local fixture workflow; no provider calls or resources. Local electricity and hardware costs are not estimated. |
| September 19 RTX PRO 6000 trial | **4.2096 total** | RunPod billing API: 4.1384 GPU + 0.0712 disk. The earlier 4.1280 balance-derived figure is superseded by this billing read. |
| Earlier trial: measured serving windows | **≈ 1.4121**, included above | Derived from 1,208.942s + 1,223.389s at the recorded $2.09/GPU-hour. Not an invoice line item. |
| Earlier trial: unallocated billed remainder | **≈ 2.7975**, included above | Billing total minus the 1.4121 measured-window estimate. Includes disk, provisioning, downloads, startup, warm-up, retries, probes, evidence collection and cleanup; no per-step allocation is available. |
| Failed community scheduling | **0 GPU charge** | [Earlier journal](prior-study/journal.md), J01: no pod created. |
| Two endpoint “dry requests” | **Not separately available** | Earlier journal, J08. Ran during paid pod time, so their cost is included in that session; they are not the free local rehearsal. |

The Episode 00 campaign roll-up is **$11.8311** from the provider billing read. Do not sum the “included above” rows a second time.

## What remains unavailable

The September 20 billing bucket is 7.6216 total (7.5486 GPU + 0.0729 disk). Billing Explorer rounds the GPU split to 6.425 H100 + 1.124 A100. Separate successful-run, per-runtime, warm-up, setup and retry costs are not available; do not divide the daily bucket equally or allocate it by request count. The older 2.19 CLI-debit note conflicts with the billing API and is superseded for publication.

The retained October AgentBench billing buckets total **19.0664** (18.8696 GPU + 0.1968 disk), but their bucket dates do not align with the retained timestamps for the six matched Episode 01 cells. They are therefore not attributed to Episode 01 on the public page. Episode 01 shows only a **3.21 protocol-time estimate**: two engine arms × three loads × (120 seconds warm-up + 300 seconds measured) = 0.70 GPU-hours, multiplied by the recorded RunPod H200 rate of 4.59 per hour. This is not an invoice allocation and excludes setup, loading, validation, retries, idle time, storage, network and taxes.

## Cleanup

The H100 [teardown record](../data/public/teardown.json) records both pods deleted and absent, including direct lookups returning not found. The earlier report records permanent deletion and an empty provider inventory after cleanup. These records document historical cleanup, not current prices or a new execution approval.
