# Study journal

Both paid runs passed preflight, runtime setup, server readiness, warmup, request validation, evidence pull, and teardown gates. Baseline completed 360/360 requests; stress completed 576/576 requests. Native metrics were captured at one-second cadence. The eBPF probe reported unavailable without blocking. Provider deletion acknowledgments, direct not-found checks, and empty inventory were verified for both pods.
