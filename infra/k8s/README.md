# Local Kubernetes deployment

For detailed scenario procedures and pass/fail criteria, use the repository's
[distributed test and cloud-readiness guide](../../TESTING.md).

This is the same project and the same six application images as Docker Compose.
Kind runs a dedicated single-node Kubernetes cluster in Docker Desktop. No cloud
account, registry push, global kubeconfig modification or paid service is needed.

## Start and verify

To start a fresh simulation on the main page at **http://127.0.0.1:18090**, run:

```powershell
python demo.py --kubernetes --reset-demo
```

This explicitly deletes the main local Kubernetes demo's bookings, payment
history, queue and database storage, then recreates the stack and initial seats.
Wait for **Fresh main demo ready**, reload the page, and click **Switch user**
before registering again. It uses already loaded images; after code changes run
normal startup first to rebuild/load them. Normal startup preserves data.
`--reset-test-env` instead resets the lab at port **18100**, which does not affect
the main page at **18090**. Neither command resets Docker Compose data.

From the repository root, with Docker Desktop using Linux containers:

```powershell
python demo.py --kubernetes --verify
```

The launcher builds the images, creates/reuses cluster `csc3104`, loads the images,
runs booking/storage checks in disposable namespace `csc3104-check`, removes that
test namespace, then deploys the main namespace `csc3104`. Open
**http://127.0.0.1:18090**. For subsequent deployment without recreating test data:

```powershell
python demo.py --kubernetes
```

`kubectl` must be installed (Docker Desktop bundles it on Windows). If Kind is not
installed, the Windows launcher downloads official v0.33.0 to ignored `.local/bin`
and verifies its published SHA-256. Other platforms need Kind installed on PATH.
The node image is pinned to Kubernetes v1.36.4 and its digest in `kind.yaml`.
Docker's `image save --platform` support is required. The launcher exports only the
node's platform and loads that archive, avoiding the Docker containerd-store
[Kind image-loading issue](https://kind.sigs.k8s.io/docs/user/known-issues/#unable-to-kind-load-docker-images).
Temporary archives are removed after loading.

The launcher always targets `.local/k8s/kubeconfig` and context `kind-csc3104`.
It never switches the global kubectl context. Compose remains available with
`python demo.py`; its volumes and booking data are separate and unchanged. Stop
the Compose stack with `python demo.py --stop` if you want to free its resources.

## What is deployed

| Kubernetes resource | Components | Reason |
| --- | --- | --- |
| Six Deployments | Frontend and five service APIs | Replaceable application Pods |
| Five Deployments | Waiting-room recovery, dispatch, allocation, seat expiry/callback and payment workers | Independent background processing and scaling |
| Two StatefulSets and PVCs | PostgreSQL and Redis, one replica each | Retain authoritative state across Pod replacement |
| Three Jobs | Seat initialization, allocator initialization, payment migrations | Complete before application rollout |
| Services | Stable internal service DNS; frontend NodePort | Internal connections and loopback browser access |
| ConfigMaps | Non-secret settings and existing database-bootstrap script | Configuration without rebuilding images |
| Secret | Database URLs/passwords and internal payment token | Credentials kept out of tracked manifests |

Application containers request 50m CPU/96 MiB RAM and are limited to 500m/256 MiB.
PostgreSQL requests 100m/128 MiB with limits of 1 CPU/512 MiB; Redis requests
100m/64 MiB with limits of 1 CPU/256 MiB. The eleven long-running application Pods
and two storage Pods request about 1.25 GiB RAM in total, excluding cluster system
Pods and temporary migration Jobs. These are starting values for local testing,
not proven production capacity.

Application containers run as UID 10001, cannot escalate privileges, drop Linux
capabilities, have read-only root filesystems and writable temporary volumes.
Service account tokens are not mounted. The frontend runs the image's existing
Waitress server in Kubernetes. PostgreSQL and Redis use their official entrypoints
and writable data volumes.

## Configuration and data

Non-secret defaults are in `local/config.yaml`. Main holds remain 300 seconds;
`--verify` uses 30-second holds only in its test namespace. `--batch-size N` is
supported by the launcher. Initial replicas are one; HPA/metrics-server and node
autoscaling are intentionally left for later measured experiments.

Random namespace-specific credentials are stored only in ignored
`.local/k8s/secrets-csc3104.json` and installed as a Kubernetes Secret. Retain this
file with the database PVCs. Losing it and generating new passwords does not
rotate passwords in an initialized database. Kubernetes Secrets are not an
encrypted secret-management system by themselves; do not commit or share the
generated files or kubeconfig. The four database roles are non-superusers and own
separate databases. This local bootstrap shares one application password; separate
migration/runtime privileges and distinct deployment credentials are later work.

PostgreSQL has one 1 GiB claim; Redis has one 1 GiB claim and AOF persistence.
Kind's default local-path StorageClass provisions the storage. Data survives
replacement of application and storage Pods, and scaling the project to zero.
**Deleting the Kind cluster deletes its node-local storage.** This is a local
development cluster, not storage HA, a backup strategy or a multi-node cluster.

Migrations are replayed on deployment as explicit Jobs. The launcher refuses to
replace an active migration Job. Do not run two deploy commands concurrently.
ConfigMap changes are followed by application restarts so processes reload their
settings; the main database and Redis volumes are preserved.

## Probes and monitoring

APIs have startup and readiness probes that check their documented readiness
endpoints. Liveness checks avoid restarting services merely because PostgreSQL or
Redis is unavailable: seat-store uses a TCP liveness check because its `/health`
endpoint checks the database. Storage has startup/readiness and TCP liveness
probes. Probe timeouts and startup budgets are explicit.

Background worker processes have no HTTP health endpoints. Kubernetes restarts a
worker that exits; a Ready worker Pod alone does not prove useful progress. The
launcher does not invent `kill -0` probes or use a shared heartbeat to claim every
worker is alive. Verify worker progress through completed allocation/payment
jobs, expiry/callback delivery, backlog state and payment's shared heartbeat:

```powershell
kubectl --kubeconfig .local/k8s/kubeconfig --context kind-csc3104 -n csc3104 get 'pods,pvc,services,jobs'
kubectl --kubeconfig .local/k8s/kubeconfig --context kind-csc3104 -n csc3104 exec deployment/payment-worker -- python service.py monitor
kubectl --kubeconfig .local/k8s/kubeconfig --context kind-csc3104 -n csc3104 logs deployment/allocation-worker --tail=50
```

## Acceptance boundaries

`--verify` runs the existing real-network booking checker inside the test
frontend Pod, through its HTTP proxy and Kubernetes Services. It covers assets,
Redis registration, duplicate requests, automatic dispatch, allocation, payment,
decline/retry, cancellation, unavailable capacity, expiry and late-payment
rejection. It then replaces the test PostgreSQL/Redis Pods and verifies that hold
records, confirmed seats, payment history, Redis records and PVC UIDs survive.
The main namespace's bookings and PVCs are never reset by this check.

This is deployment and persistence acceptance. Crashes during unfinished work,
network fault injection, node failure, load/autoscaling, fairness comparisons and
cloud cost analysis remain subsequent experiments. The frontend still proxies
trusted internal/admin operations: keep the mapped port on loopback until user
authentication, scoped checkout-token delivery and admin authorization are ready.

## Stop without deleting data

```powershell
python demo.py --kubernetes --stop
```

This scales only namespace `csc3104` Deployments and StatefulSets to zero. It keeps
PVCs, Secrets, configuration and the local cluster. Start with the same command
without `--stop` to resume. Do not delete the main namespace, its PVCs or the Kind
cluster unless you explicitly intend to discard that deployment's local data.
