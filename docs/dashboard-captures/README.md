# Episode 0 dashboard captures

Captured from the native React dashboard at `http://127.0.0.1:5173/` on
2026-09-21. Each figure is provided at a 1,440 px desktop viewport and a
720 px article viewport. The PNG width is the dashboard content width after
page margins, so the resulting images are 1,324 px and 662 px wide.
The 720 px delivered-work figure was captured from the native `.work-figure`
element after verifying all six workload ticks, all 12 runtime values, and no
horizontal chart overflow (632 px scroll width and client width).

## Capture inventory

| Figure | Files | Source and aggregation | Suggested alt text |
| --- | --- | --- | --- |
| Measured performance | `01-performance-1440.png`, `01-performance-720.png` | `dashboard/src/data/latest.json`; aggregate output tokens divided by measured wall time, plus client TTFT p50. Workloads are paired categorical input-length/concurrency settings, not a concurrency sweep. | Grouped SGLang and vLLM output-rate bars and median time-to-first-token dots across six paired H100 workloads; vLLM leads output rate in five of six cells and has lower TTFT in five of six cells. |
| Delivered work | `02-delivered-work-1440.png`, `02-delivered-work-720.png` | `dashboard/src/data/latest.json`; successful output-token total divided by successful requests. Gray lines are configured 64-token baseline and 128-token stress caps from `public/reproduction.md`, not measurements. | Grouped bars compare mean delivered output tokens per successful request with configured request caps; the two longest-input vLLM cells finish below their 64-token and 128-token caps. |
| Runtime-native telemetry | `03-native-telemetry-1440.png`, `03-native-telemetry-720.png` | `public/telemetry-summary.csv`; vLLM phase points are medians of per-repetition mean duration. KV-cache and waiting-request points are medians of repetition-level peaks. SGLang phase durations are unavailable and remain visibly absent. | Three categorical plots show vLLM prefill and decode duration summaries, paired runtime KV-cache peaks, and paired waiting-request peaks across all six workloads; phase coverage is available only for vLLM. |
| Device peaks | `04-gpu-peaks-1440.png`, `04-gpu-peaks-720.png` | `public/gpu-summary.json`; maxima of one-second samples for each runtime and run, not medians, traces, or saturation duration. | Peak GPU utilization is 100 percent for SGLang and vLLM in baseline and stress runs, with a supporting table of peak memory, power, temperature, and sample counts. |

No client latency metric was used to infer prefill or decode timing. KV-cache
percentages retain each runtime's native denominator, which is not proven
equivalent across engines. The GPU peak panel does not establish sustained
utilization or a bottleneck.

## File integrity

| File | Pixels | SHA-256 |
| --- | ---: | --- |
| `01-performance-1440.png` | 1324 × 479 | `23ab896a7bc4784f16752f67241e88c3d9275ea257018e593c9f0ceeda92ba93` |
| `01-performance-720.png` | 662 × 956 | `96447a2b242250713483a897e6e621743cfa4d6af366cfd6dccd7f4e10cf9760` |
| `02-delivered-work-1440.png` | 1324 × 697 | `f0f2adb996aed2468c1ee29e18130628661aad3200f76fe2e66f58ed7f110b77` |
| `02-delivered-work-720.png` | 662 × 415 | `37cdd569c3ae2167d4e43b5349292186889b7da03e4d2471dc1b7b25cb015997` |
| `03-native-telemetry-1440.png` | 1324 × 1248 | `ae7f1393cacf48bee8ccdb0e1d7273a952a74fa94d67aff4b998d8f9ab233a07` |
| `03-native-telemetry-720.png` | 662 × 1445 | `5ab606c77796c56494895a203631126d8f1d1e8787bf7299f1492cbf7fccbd87` |
| `04-gpu-peaks-1440.png` | 1324 × 741 | `6f0e2afd7c8aaa667945df7e3e9329d0c3311d12b704841bcdc9ebf538067847` |
| `04-gpu-peaks-720.png` | 662 × 572 | `7b374e3916217f085212bbc553a16245378e423f0e98aeda64cbf297d9bb34e0` |

The dashboard now opens on a series index. To revisit these same chart panels,
choose Episode 0 or open `http://127.0.0.1:5173/#episode-0`. The captures and
underlying historical evidence have not changed.
