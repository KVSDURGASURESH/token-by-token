 # Token by Token — Docker and Kubernetes (Helm) deployment plan

 Status: plan (not implemented). Date: 2026-10-09. Base: `main` @ 050bb77.
 Scope: containerize the website for Kubernetes and package the deployment as a
 Helm chart. This plan reuses the repository's existing Dockerfile and compose
 file; it does not redesign the application.

 ## 1. Goals and non-goals

 Goals

 - One reproducible image (and a small static image) that runs the public site
   and the operator console exactly as `compose.yaml` runs them today.
 - A Helm chart that deploys the website to a Kubernetes cluster with sane
   defaults, optional observability, and no secrets in values.
 - The same security posture as compose (non-root, read-only rootfs,
   no-new-privileges, dropped capabilities, loopback-only bridge by default).
 - Verification that uses the repository's existing acceptance tests.

 Non-goals (for this iteration)

 - No GPU workloads on the cluster. Engine deployments (vLLM/SGLang) stay on
   pods/RunPod; this chart serves the website, not the engines. A section is
   included for the future benchmark-job pattern, but it is out of scope.
 - No migration of the publication pipeline, no changes to the React app.

 ## 2. What already exists

 `Dockerfile` (two stages):

 - Builder: `node:24.9.0-alpine`, `npm ci --ignore-scripts`, `npm run build`
   (TypeScript check + Vite build of both entry points: `index.html` public
   site and `legacy.html` operator lab).
 - Runtime: `python:3.12.12-slim`, non-root user `inference-lab` (uid 10001),
   copies `src/`, `scripts/episode1_playground.py`, the dashboard `dist/`,
   healthcheck on `GET /healthz`, `EXPOSE 8765`, entrypoint
   `episode1_playground.py serve --host 0.0.0.0 --port 8765 --profiles
   /config/profiles.json --dashboard-dir /app/dashboard/dist`.

 `compose.yaml` runs three services, all loopback-published:

 | Service | Image | Port | Notes |
 |---|---|---|---|
 | `episode-console` | built from `Dockerfile` | 8765 | bridge + both UIs; `read_only` rootfs, `tmpfs /tmp`, `cap_drop ALL`, 2 CPU / 1 GiB limits |
 | `victoria-metrics` | `victoriametrics/victoria-metrics:v1.151.0` | 8428 | 30d retention, scrape config from `deploy/victoria-metrics/scrape.yml`, DCGM targets file |
 | `grafana` | `grafana/grafana:12.2.0` | 3000 | anonymous read-only viewer, sign-up disabled, provisioned datasources + dashboards from `deploy/grafana/` |

 Environment the image consumes at runtime: `VLLM_API_KEY`, `SGLANG_API_KEY`,
 `/config/profiles.json` (episode run profiles). Build-time variables the site
 honors: `VITE_PUBLIC_GRAFANA_ENABLED` (gates the public "Live dashboard" link
 to `https://graph.endlesstokens.ai`) and `VITE_UMAMI_SCRIPT_URL` /
 `VITE_UMAMI_WEBSITE_ID` / `VITE_UMAMI_DOMAINS` (optional privacy-first
 analytics; disabled when absent, see `docs/analytics.md`).

 Key property: the public site is fully static. Every public page is served
 from the Vite bundle with committed JSON; the Python bridge is only needed by
 the operator lab UI (`legacy.html`), the quick-test endpoints, and

## 3. Deployment topology

Three tiers, each independently deployable; the chart installs any subset.

```
                         Ingress (TLS)
                          |        \
                    site svc    console svc (auth)
                     |              |
                [static]        [console]
              nginx:alpine      episode1_playground
              /usr/share/html   serve + bridge :8765

      [victoria-metrics]  [grafana]   (optional observability tier,
         :8428                :3000    cluster-internal only)
```

 T1 — Public site (required). The Vite build served by nginx:alpine. No
 Python, no secrets, stateless, horizontally scalable. This is the only
 component that should be exposed publicly.

 T2 — Operator console (optional). The existing `Dockerfile` image running
 `episode1_playground.py serve`. Serves the legacy lab UI plus the bridge API
 (quick test, episode runs, canonical launch endpoints). Must never be
 exposed without authentication: it can start local benchmark traffic.

 T3 — Observability (optional). VictoriaMetrics + Grafana exactly as in
 `compose.yaml`. Cluster-internal; never public (the public site links to the
 separate public Grafana only when `VITE_PUBLIC_GRAFANA_ENABLED` was set at
 build time).

### Image strategy

1. **Console image** — keep the current `Dockerfile` unchanged except adding
   an `ARG` for the site build vars so the public build flags can be baked at
   image build time:

   ```dockerfile
   FROM node:24.9.0-alpine AS dashboard-builder
   ARG VITE_PUBLIC_GRAFANA_ENABLED=false
   ARG VITE_UMAMI_SCRIPT_URL=
   ARG VITE_UMAMI_WEBSITE_ID=
   ARG VITE_UMAMI_DOMAINS=
   ENV VITE_PUBLIC_GRAFANA_ENABLED=$VITE_PUBLIC_GRAFANA_ENABLED \
       VITE_UMAMI_SCRIPT_URL=$VITE_UMAMI_SCRIPT_URL \
       VITE_UMAMI_WEBSITE_ID=$VITE_UMAMI_WEBSITE_ID \
       VITE_UMAMI_DOMAINS=$VITE_UMAMI_DOMAINS
   ...
   ```

   Build two variants from the same source:
   - `token-by-token/site:<tag>` — the builder stage's `dist/` copied into
     `nginx:alpine` (static image; a second `Dockerfile.site` multi-stage off
     the same builder stage).
   - `token-by-token/console:<tag>` — the existing runtime stage.

   Both must be tagged with an immutable digest and the digest recorded
   (the repo already treats image digests as evidence-grade provenance).

2. **Observability images** — pin the exact versions compose uses
   (`victoria-metrics:v1.151.0`, `grafana:12.2.0`); the chart references them
   via values so the registry can be overridden.

## 4. Helm chart design

Chart name: `token-by-token` (release name e.g. `inference-lab`).

```
charts/token-by-token/
  Chart.yaml                     # apiVersion v2, appVersion from git describe
  values.yaml
  values.public.yaml             # public deployment: site only, no console
  templates/
    _helpers.tpl
    # T1 site
    site-deployment.yaml         # nginx:alpine, /usr/share/html read-only
    site-service.yaml
    site-ingress.yaml
    # T2 console (optional)
    console-deployment.yaml      # single replica, /tmp tmpfs, non-root
    console-service.yaml
    console-ingress.yaml         # only if auth enabled
    console-secret.yaml          # API keys + profiles.json from Secret
    # T3 observability (optional)
    vm-statefulset.yaml
    vm-service.yaml
    grafana-deployment.yaml
    grafana-service.yaml
    dashboards-configmap.yaml    # from deploy/grafana/dashboards
    scrape-configmap.yaml        # from deploy/victoria-metrics/scrape.yml
  tests/                         # helm unittest (optional)
```

### values.yaml (defaults shown; every secret is empty and injected)

```yaml
global:
  imageRegistry: ""            # e.g. ghcr.io/KVSDURGASURESH
  imagePullSecrets: []

site:
  enabled: true
  image: token-by-token/site
  tag: ""                       # required unless .digest set
  digest: ""
  replicas: 2
  resources: {requests: {cpu: 50m, memory: 64Mi},
              limits: {cpu: 200m, memory: 128Mi}}
  security:                     # mirrors compose posture
    runAsNonRoot: true
    runAsUser: 101              # nginx
    readOnlyRootFilesystem: true
    allowPrivilegeEscalation: false
    capabilities: {drop: ["ALL"]}

console:
  enabled: false                # never on by default
  image: token-by-token/console
  tag: ""
  digest: ""
  # bridge must stay loopback-internal; exposed only via authed ingress
  replicas: 1                   # keep at 1: bridge state is local
  profiles: ""                  # JSON, or use profilesSecret
  profilesSecret: ""            # name of Secret with profiles.json
  secrets: {secretName: ""}     # Secret with VLLM_API_KEY/SGLANG_API_KEY
  resources: {requests: {cpu: 500m, memory: 512Mi},
              limits: {cpu: "2", memory: 1Gi}}

ingress:
  enabled: true
  className: ""                 # e.g. ingress-nginx / traefik
  host: tokenbytoken.example.com
  tls: {enabled: true, secretName: ""}
  console:
    path: /lab
    auth:
      enabled: true             # required when console.enabled
      method: basic             # or external: oauth2-proxy / gateway policy
      secretName: ""            # htpasswd Secret

observability:
  enabled: false
  victoriaMetrics:
    image: victoriametrics/victoria-metrics
    tag: v1.151.0
    retentionDays: 30
    persistence: {size: 10Gi, storageClass: ""}
    resources: {requests: {cpu: 250m, memory: 1Gi},
                limits: {cpu: "1", memory: 2Gi}}
  grafana:
    image: grafana/grafana
    tag: 12.2.0
    anonymousViewerOnly: true   # same flags as compose.yaml
    resources: {requests: {cpu: 100m, memory: 256Mi},
                limits: {cpu: "1", memory: 512Mi}}
```

### Template rules

- `site-deployment`: nginx serving `dist/` from the site image; ConfigMap
  only for nginx.conf (gzip, `Cache-Control` for hashed assets, no
  `server_tokens`, HSTS behind TLS). `/healthz` -> 200 static page for
  liveness/readiness probes.
- `console-deployment`: env from Secret; `emptyDir` (sizeLimit 64Mi) for
  `/tmp`; single replica; readiness probe `GET /healthz`.
- `site-ingress` / `console-ingress`: separate Ingress resources; console
  ingress rendered only when `console.enabled && ingress.console.auth.enabled`.
- `dashboards-configmap` / `scrape-configmap`: file contents copied from
  `deploy/grafana/dashboards/` and `deploy/victoria-metrics/` at chart build
  time (or read from a values block in CI). Keep the repo files as the single
  source of truth.
- Labels everywhere: `app.kubernetes.io/name`, `/instance`, `/part-of`,
  `/managed-by: Helm` (agentbench's `deploy/k8s` uses the same
  `app.kubernetes.io/part-of` convention — stay compatible).

## 5. Observability tier on Kubernetes

- VictoriaMetrics as a StatefulSet with PVC (compose uses a named volume;
  30-day retention flag carried over from `compose.yaml`).
- Grafana Deployment with the exact anonymous-viewer env block from
  `compose.yaml` (sign-up off, login form disabled, analytics off);
  provisioning files from the existing `deploy/grafana/provisioning/`.
- Scrape: point VictoriaMetrics' `promscrape.config` at the console
  `http://<release>-console:8765/metrics` (and the site pod's nginx
  metrics endpoint if enabled). DCGM targets stay an empty file unless a
  GPU exporter is later added to the cluster.
- No dashboards or metrics ever published publicly; the public site's
  "Live dashboard" link remains governed by `VITE_PUBLIC_GRAFANA_ENABLED`
  and points at the public Grafana host, not this cluster.

## 6. Future: GPU benchmark jobs on the cluster (out of scope, pattern only)

When episodes move to cluster GPUs, the pattern (mirroring agentbench's
`deploy/k8s/` campaign tooling) is:

- Node pool with the NVIDIA device plugin; DCGM exporter DaemonSet for GPU
  metrics into VictoriaMetrics; toleration/taint for `nvidia.com/gpu`.
- Engines as long-running Deployments (one pod per model+engine combo,
  exposed via Service; ports 8000 engine / 7860 exporter, matching the
  conventions in agentbench's `tools/deploy_inference.py`).
- Benchmarks as `Job`s (run-to-completion, `backoffLimit: 0`, TTL after
  finish), each Job writing results to a PVC or object storage; a "guard"
  CronJob that force-deletes engine pods after a wall-clock cap. The
  deletion-with-provider-side-verification requirement from
  `docs/runpod-setup.md` maps to job TTL + pod deletion + a verification
  script that proves the resources are gone before a new one is created.

 This is deliberately not part of the chart yet. When the operator wrapper's
 container/k8s adapter lands (episode presets plan, §9 Phase 4), the wrapper
 runs its two jobs (deploy/attest, then AgentBench + promotion) against
 these resources instead of ad-hoc Jobs.

## 7. Implementation plan (ordered)

1. **Images.** Add the `ARG`s to `Dockerfile`; add `Dockerfile.site`
   (builder stage + `nginx:alpine`). Build both; tag with the git sha and
   record the digests. Verify the console image against `compose.yaml`
   behavior (same command, same healthcheck).

2. **Chart scaffold.** `helm create` the chart; lay out the templates from
   §4; `values.public.yaml` = site only. `helm lint` + `helm template` with
   (a) public values, (b) public + console + observability values; review
   every rendered resource by hand.

3. **Dev cluster deploy.** Install ingress controller (if absent), TLS cert
   (cert-manager or static), then `helm install`. Check: site 200s on the
   public host, console 401/403 without auth and 200 with auth, VM +
   Grafana cluster-internal only.

4. **Observability wiring.** Point `scrape-configmap` at the console
   service; confirm the existing dashboards render (they were built for the
   compose deployment's metric names).

5. **CI job.** Build -> push (digest) -> `helm lint`/`template` -> install to
   a disposable namespace -> run the acceptance tests against the ingress
   URL -> uninstall.

6. **Production values.** Set real host, TLS, registry, Umami variables
   (production domain allowlist) and `VITE_PUBLIC_GRAFANA_ENABLED` only
   after the public Grafana is verified read-only (README requirement).

## 8. Verification

- Build-time: `npm --prefix dashboard run check && npm --prefix dashboard
  run build`; `python3 scripts/check_publication_privacy.py --root
  dashboard/dist --files-only` (same gate as the static publication
  lifecycle in README §"Static publication lifecycle").
- Deployed: `node tests/dashboard_offline_acceptance.cjs <dist>` locally;
  `node tests/dashboard_site_v2_acceptance.cjs http://127.0.0.1:4173/`
  against the dev server, and the same script pointed at the ingress URL
  (it takes a base URL argument) after deployment.
- Console: `curl <console>/healthz` = 200; unauthenticated ingress path
  returns 401/403; quick-test endpoint refuses to run canonical/paid paths
  (existing fail-closed behavior, unchanged).
- Secrets audit: `helm template` output contains no API keys, no Umami
  website id in values (build-time only), no Grafana credentials.

## 9. Open questions

- Image registry: GHCR of this account, or a private registry?
- Ingress controller and TLS: cert-manager with which issuer?
- Console auth: basic (htpasswd) is the minimal option; is there an existing
  IdP (oauth2-proxy / Cloudflare Access) that should be used instead?
- Public domain for the site, and whether the site and console live on the
  same host (different paths) or separate hosts.
- Retention/size: 30-day VM retention and a 10 GiB PVC assumed; confirm the
  cluster's storage class.
 `/metrics` for the local VictoriaMetrics scrape.