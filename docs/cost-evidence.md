# Episode 0 — cost evidence

Amounts below describe two different historical studies. They are retained provider-balance debits or explicitly labeled estimates, not a transaction-level invoice. No new paid experiment was run for this publication.

| Activity | Amount (USD) | Evidence and interpretation |
|---|---:|---|
| September 20 H100 baseline + stress | **≈ 2.19** | [Retained plan](../data/public/plan.json), `observed_cli_debit_usd`, and [report](../data/public/report.md). Rounded conservative CLI debit for both runs combined. |
| Offline fixture rehearsal / local dashboard | **0 provider charge** | Local fixture workflow; no provider calls or resources. Local electricity and hardware costs are not estimated. |
| September 19 RTX PRO 6000 trial | **4.1280** | [Earlier report](prior-study/report.md), “Cost and limitations”: aggregate session charge from starting/final provider balances. |
| Earlier trial: measured serving windows | **≈ 1.4121**, included above | Derived from 1,208.942s + 1,223.389s at the recorded $2.09/GPU-hour. Not an invoice line item. |
| Earlier trial: remaining session time | **≈ 2.7159**, included above | Residual after subtracting the measured-window estimate. Includes provisioning, downloads, startup, warm-up, retries, probes, evidence collection and cleanup; no per-step allocation is available. |
| Failed community scheduling | **0 GPU charge** | [Earlier journal](prior-study/journal.md), J01: no pod created. |
| Two endpoint “dry requests” | **Not separately available** | Earlier journal, J08. Ran during paid pod time, so their cost is included in that session; they are not the free local rehearsal. |

The roll-up across both studies is **approximately $6.32**. It is arithmetic from the retained amounts, not a provider-reported total. Do not sum the two “included above” rows a second time.

## What remains unavailable

Separate H100 baseline/stress costs, per-runtime H100 costs, individual retry costs and a provider invoice/transaction export were not retained. Do not divide the combined debit equally or allocate it by request count. No genuine billing screenshot is present in the retained evidence; a console screenshot can only be added after authenticated read-only access and verification of the relevant date range.

## Cleanup

The H100 [teardown record](../data/public/teardown.json) records both pods deleted and absent, including direct lookups returning not found. The earlier report records permanent deletion and an empty provider inventory after cleanup. These records document historical cleanup, not current prices or a new execution approval.
