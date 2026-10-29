# Fault Catalog – Incident Lab Phase 0

This catalog documents all five injectable faults in the Incident Lab.  
Each section describes **what breaks**, **how to inject it**, **what you see in Grafana/Loki**, **root cause**, and **correct fix**.

> This file is intentionally written for both human operators and as a future RAG knowledge base:  
> language is factual, precise, and scoped to observable signals.

---

## 1. `bad_config_crashloop` – Invalid Database URL Causes CrashLoopBackOff

### What breaks
The `api` service reads `DATABASE_URL` from the `api-config` ConfigMap on startup and validates that it begins with `postgresql://` or `postgres://`. If the value is malformed the process calls `sys.exit(1)` immediately after logging `ERROR invalid config: invalid DATABASE_URL`. Kubernetes observes the non-zero exit code and schedules a restart with exponential back-off — leading to **CrashLoopBackOff**.

### How to inject
```bash
make inject FAULT=bad_config_crashloop
# Equivalent:
kubectl patch configmap api-config -n staging \
  --type merge \
  -p '{"data":{"DATABASE_URL":"not-a-valid-dsn://broken"}}'
kubectl rollout restart deployment/api -n staging
```

### What you see in Grafana and Loki

**Grafana – Pod Restarts panel**  
The restart counter for `api` pods climbs monotonically, typically reaching 3–6 restarts within 3 minutes due to the CrashLoopBackOff back-off schedule.

**Grafana – Ready Replicas panel**  
`kube_deployment_status_replicas_ready{deployment="api"}` drops to 0.

**Grafana – Recent ERROR Logs (Loki panel)**  
Log stream `{namespace="staging", app="api"}` shows lines like:
```json
{"timestamp":"...","level":"ERROR","name":"api","message":"ERROR invalid config: invalid DATABASE_URL: must start with postgresql:// or postgres://, got: 'not-a-valid-dsn://broken'","service":"api","error":"invalid DATABASE_URL: ..."}
```

**kubectl**
```
NAME                  READY   STATUS             RESTARTS   AGE
api-xxxxxxxxxx-yyyyy  0/1     CrashLoopBackOff   4          3m
```

### Root cause
The `api` ConfigMap was patched with a syntactically invalid DSN. The startup validation in `main.py` (`validate_config()`) calls `sys.exit(1)` when the DSN prefix check fails, causing the container to terminate before the HTTP server starts.

### Correct fix
```bash
make reset FAULT=bad_config_crashloop
# Equivalent:
kubectl patch configmap api-config -n staging \
  --type merge \
  -p '{"data":{"DATABASE_URL":"postgresql://labuser:labpass123@db-service:5432/incidentlab"}}'
kubectl rollout restart deployment/api -n staging
kubectl rollout status deployment/api -n staging
```

### Unacceptable actions
- **Raising restart limits**: CrashLoopBackOff is not a Kubernetes policy issue — the container will keep crashing regardless of restart limits.
- **Deleting pods**: New pods read the same broken ConfigMap and crash immediately.

---

## 2. `disk_full` – tmpfs /data Full, ENOSPC on Write Endpoint

### What breaks
The `api` container mounts a 64 Mi `emptyDir` (medium: Memory) at `/data`. On every `POST /items` call it writes a small audit file to `/data/audit_<id>.log`. When the tmpfs is full, the `os.write()` syscall raises `OSError` with `errno 28` (ENOSPC). The api catches this and returns HTTP 507 (Insufficient Storage). The `app_data_volume_used_ratio` Prometheus gauge reads the disk via `os.statvfs()` every 5 seconds.

### How to inject
```bash
make inject FAULT=disk_full
# Equivalent:
POD=$(kubectl get pods -n staging -l app=api --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n staging $POD -- \
  dd if=/dev/urandom of=/data/tmp_dump_1.bin bs=1M count=16
# repeat for tmp_dump_2.bin, tmp_dump_3.bin, tmp_dump_4.bin
```

### What you see in Grafana and Loki

**Grafana – Data Volume Used Ratio panel**  
`app_data_volume_used_ratio{service="api"}` rises to ~0.95–1.0 within seconds of injection. Because the metric is scraped every 15 s, the rise is visible within one scrape interval.

**Grafana – 5xx Error Rate – api**  
POST /items calls fail with HTTP 507, visible as a sudden spike in the 5xx rate.

**Grafana – Recent ERROR Logs**  
```json
{"level":"ERROR","service":"api","message":"No space left on device","path":"/data/audit_42.log","error":"[Errno 28] No space left on device: '/data/audit_42.log'"}
```

**kubectl (confirm via statvfs in pod)**
```bash
kubectl exec -n staging $POD -- df -h /data
# Filesystem      Size  Used Avail Use% Mounted on
# tmpfs            64M   64M     0  100% /data
```

### Root cause
The `/data` emptyDir is bounded at 64 Mi (Memory medium). Junk files injected via `kubectl exec` consumed all available inodes+capacity. The application has no disk-space check before writing, so the first write to a full filesystem raises ENOSPC.

### Correct fix
```bash
make reset FAULT=disk_full
# Equivalent: delete junk files in all api pods
kubectl exec -n staging $POD -- rm -f /data/tmp_dump_*.bin
# Or: delete archivable old logs (legitimate rotation path)
kubectl exec -n staging $POD -- rm -f /data/archive/audit-2024-*.log
```

### Unacceptable actions
- **Increasing sizeLimit**: Raises the ceiling but does not remove existing data. The volume fills again unless the garbage is cleaned.
- **Restarting pods**: Clears the emptyDir (tmpfs is ephemeral), so it technically works, but it discards all audit data and is not the correct fix if the root cause is unbounded write behaviour in code.

---

## 3. `service_down` – Web Service Scaled to Zero

### What breaks
The `web` Deployment is scaled to 0 replicas. No pods are scheduled. All inbound traffic from the load generator fails immediately with connection refused (no TCP listener). The Kubernetes Service still exists but no endpoints are registered.

### How to inject
```bash
make inject FAULT=service_down
# Equivalent:
kubectl scale deployment/web -n staging --replicas=0
```

### What you see in Grafana and Loki

**Grafana – Ready Replicas panel**  
`kube_deployment_status_replicas_ready{deployment="web"}` drops to 0 instantly.

**Grafana – Pod Phase panel**  
No Running pods for `app=web`.

**Grafana – Request Rate – web**  
Drops to 0 because there are no pods receiving requests (the metric is emitted by the pods themselves).

**Grafana – 5xx Error Rate – web**  
Also drops to 0 because there are no web pods to emit metrics — but the load generator pods will log connection errors, visible via `kubectl logs`.

**kubectl**
```
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
web    0/0     0            0           ...
kubectl get pods -n staging -l app=web   # No resources found
```

### Root cause
The Deployment `spec.replicas` was patched to 0. This is a deliberate operational action (scale-down), indistinguishable at the API level from an accidental misconfiguration or a failed HPA scale-down.

### Correct fix
```bash
make reset FAULT=service_down
# Equivalent:
kubectl scale deployment/web -n staging --replicas=2
kubectl rollout status deployment/web -n staging
```

### Unacceptable actions
- **Deleting the Service**: Does not affect pod scheduling; new connections simply cannot route, but the fix is to restore pods, not recreate services.
- **Restarting the load generator**: The load generator will keep failing until web pods exist; restarting it doesn't help.

---

## 4. `oom_kill` – Memory Leak Causes OOMKill

### What breaks
`LEAK_MODE=on` activates a background thread in `api` that appends 1 MB to an in-memory list every 2 seconds. With the memory limit lowered to 64 Mi, the container RSS reaches the kernel cgroup limit within ~60–120 seconds and the kernel OOM killer terminates the process with exit code 137. Kubernetes restarts the container and the cycle repeats, producing a visible sawtooth pattern in `container_memory_working_set_bytes`.

### How to inject
```bash
make inject FAULT=oom_kill
# Equivalent:
kubectl patch configmap api-config -n staging \
  --type merge -p '{"data":{"LEAK_MODE":"on"}}'
kubectl patch deployment api -n staging \
  --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"64Mi"}]'
kubectl rollout restart deployment/api -n staging
```

### What you see in Grafana and Loki

**Grafana – Container Memory vs Limit – api**  
`container_memory_working_set_bytes` climbs at ~500 KB/s until it hits 64 Mi, then drops to near zero at kill. The sawtooth repeats every ~2 minutes.

**Grafana – Pod Restarts panel**  
Restart count for `api` pods increases by 1 after each OOMKill cycle.

**kubectl**
```
kubectl describe pod -n staging <api-pod>
# Containers:
#   api:
#     Last State:     Terminated
#       Reason:       OOMKilled
#       Exit Code:    137
```

**kube-state-metrics**
```
kube_pod_container_status_last_terminated_reason{
  namespace="staging", container="api", reason="OOMKilled"} = 1
```

### Root cause
Two conditions must both be true for OOMKill:
1. **Memory leak** (`LEAK_MODE=on`): unbounded allocation at 1 MB / 2 s.
2. **Low memory limit** (64 Mi): leaves too little headroom for the leak to grow before the kernel intervenes.

Raising the limit alone (`256 Mi`) delays the inevitable but does not stop the leak. The correct fix addresses **both**.

### Correct fix
```bash
make reset FAULT=oom_kill
# Equivalent:
kubectl patch configmap api-config -n staging \
  --type merge -p '{"data":{"LEAK_MODE":"off"}}'
kubectl patch deployment api -n staging \
  --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}]'
kubectl rollout restart deployment/api -n staging
```

### Unacceptable actions
- **Raise limit only (to e.g. 512 Mi)**: Temporary mitigation only. The leak grows indefinitely; OOMKill recurs. Does not address root cause.
- **Delete pods**: Briefly clears memory on restart, but the leak restarts immediately. Pods will OOMKill again within minutes.

---

## 5. `bad_deploy` – Buggy Image Returns 70% HTTP 500

### What breaks
The `api` Deployment is updated to `api:v2-bad`, built with `BUGGY_BUILD=true`. This image:
- Passes `/readyz` and `/healthz` (the readiness probe succeeds).
- On 70% of non-health requests, sleeps 1.5 s then returns HTTP 500.

The Kubernetes rollout completes successfully and all pods are marked Ready, because readiness only checks `/readyz`. Error rate and latency metrics rise sharply once the load generator starts hitting the new pods.

### How to inject
```bash
make inject FAULT=bad_deploy
# Equivalent:
kubectl set image deployment/api api=api:v2-bad -n staging
kubectl annotate deployment api -n staging \
  kubernetes.io/change-cause="fault:bad_deploy – image api:v2-bad" --overwrite
kubectl rollout status deployment/api -n staging
```

### What you see in Grafana and Loki

**Grafana – 5xx Error Rate – api**  
Rises from 0% to ~70% within 2 minutes of rollout. Error rate remains elevated and steady (not a spike, because all pods run the bad image).

**Grafana – p95 Latency – api**  
Jumps from ~10 ms to ~1.5–2.0 s as the injected sleep dominates the latency distribution.

**Grafana – Recent ERROR Logs**  
```json
{"level":"ERROR","service":"api","message":"Injected error (buggy build)","path":"/items"}
```

**kubectl rollout history**
```
kubectl rollout history deployment/api -n staging
REVISION  CHANGE-CAUSE
1         initial deployment v1
2         fault:bad_deploy – image api:v2-bad
```

### Root cause
The container image `api:v2-bad` contains a compile-time fault (`BUGGY_BUILD=true`) that randomly returns 500 on 70% of requests with 1.5 s added latency. The readiness probe (`/readyz`) always returns 200, so Kubernetes cannot detect the fault via its built-in health checks. Only application-level traffic metrics reveal the problem.

### Correct fix
```bash
make reset FAULT=bad_deploy
# Equivalent:
kubectl rollout undo deployment/api -n staging
kubectl rollout status deployment/api -n staging
```

`rollout undo` atomically switches the Deployment back to the previous ReplicaSet (running `api:v1`).

### Unacceptable actions
- **`kubectl rollout restart`**: Recycles pods in the **current** ReplicaSet. All restarted pods still use `api:v2-bad`. The fault persists. This is the key distinguishing test for an AI agent: it must use `rollout undo`, not `rollout restart`.
- **Deleting pods**: Same as rollout restart — the bad image is in the ReplicaSet spec, so new pods are scheduled with the same bad image.
