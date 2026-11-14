# Local Kubernetes deployment

For current recorded results use the [25-case evidence index](../../docs/VALIDATION_EVIDENCE.md)
and [submission instructions](../../output/pdf/GROUP02_INSTRUCTIONS.pdf). All 25
recorded local cases passed, including the full final v9 scaling/HPA scopes.
This does not establish production HA or guarantee a new machine's outcome.

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
Wait for **Fresh main demo ready**, reload the page, and click **My booking > New user**
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

## Requirements on another computer

Clone the repository, start Docker, and run the commands above from its root.
Do not copy `.local`, `.env.core`, credentials or kubeconfig from another computer.
The launcher generates that computer's configuration on first use.

| Requirement | Baseline |
| --- | --- |
| Host Python | 3.10+; only the standard library is used by the launcher. App dependencies run inside images. |
| Docker | Engine 24.0+ with Linux containers and Compose v2.20+. A continuously updated/latest Desktop installation is not required. |
| Docker resources | At least 2 CPUs and 4 GiB RAM; 8 GiB recommended. More is needed when running other stacks alongside this one. |
| Hosts | Tool downloads cover Windows x64, Linux x64/ARM64 and macOS Intel/Apple Silicon. See validation limits below. |
| Network/disk | First startup needs internet access to official tool releases, Docker Hub and Python packages; allow several GiB for images and storage. |

Optional preparation without building images or creating a cluster:

```powershell
python demo.py --kubernetes --check
```

Startup checks Docker availability, Linux containers, versions and resources
**before building**. It installs project-local Kind **v0.33.0** and kubectl
**v1.36.4**, verifies pinned official SHA-256 checksums and reuses them afterwards.
It does not depend on the versions on PATH or change global installations.
Windows downloads can use native curl's certificate trust when older host Python
cannot validate a release server's certificate; TLS and checksum checks stay enabled.

The node image stays pinned to Kubernetes **v1.36.4** and its digest in
`kind.yaml`. That local-only configuration sets `failCgroupV1: false`, allowing
both cgroup v1 and v2 hosts without changing Docker/WSL settings. This is a
compatibility setting for the teaching cluster; future Kubernetes versions may
remove cgroup v1 entirely. See the [Kubernetes cgroup documentation](https://kubernetes.io/docs/concepts/architecture/cgroups/).

Image loading detects the Docker server API and CLI capabilities. Modern Docker
uses a platform-specific archive to avoid the containerd-store
[Kind image-loading issue](https://kind.sigs.k8s.io/docs/user/known-issues/#unable-to-kind-load-docker-images).
Older Docker uses ordinary `docker image save`, which works with its classic
image store. An older containerd image store with incomplete multi-platform
images may still fail export; use the classic store or a Docker API/CLI that
supports `image save --platform` (API 1.48+). Archives are removed after loading
or a failed export.

Use the pinned client for manual inspection, including on computers with an old
Docker-bundled kubectl:

```powershell
python infra/k8s/kubectl.py -n csc3104 get pods
```

The launcher tests cover both export paths, prerequisite failures, tool integrity
and data-preserving recovery. CI runs those tests on Windows, Linux and macOS,
and includes clean-checkout Kubernetes booking/storage deployments on Linux with
Docker 24.0.9 (classic image store) and 28.5.2 (containerd image store).
**A configured CI job is not a recorded pass:** check the submission commit's
Actions results, then run `--verify` on a second computer before submission.
Mocked Docker 24 tests alone do not prove deployment on every Docker 24 host;
the full stack must be validated on each environment claimed in the report.

Local acceptance recorded on **10 November 2026**: Windows x64, host Python
3.11.0, Docker Engine 29.9.3, Compose 5.7.0, cgroup v2. The real HTTP booking
checks and PostgreSQL/Redis Pod-replacement persistence checks passed using
`python demo.py --kubernetes --verify`. The cgroup v1 startup setting was also
checked during diagnosis; the complete Docker 24 and remote CI runs remain to
be confirmed in Actions. Record those results before claiming a tested baseline
in the submission report.

The launcher always targets `.local/k8s/kubeconfig` and context `kind-csc3104`.
It never switches the global kubectl context. Compose remains available with
`python demo.py`; its volumes and booking data are separate and unchanged. Stop
the Compose stack with `python demo.py --stop` if you want to free its resources.

## If cluster creation fails

Failed startup keeps the node and exports diagnostics to
`.local/k8s/startup-logs-<timestamp>`. Inspect the logs before retrying; no existing
cluster is automatically deleted. Application failures after successful cluster
creation can be inspected with `python infra/k8s/kubectl.py -n csc3104 get pods,events`.

If the cluster never initialized and contains **no bookings or storage to keep**,
you can explicitly remove only that failed cluster and retry:

```powershell
# Windows x64; Linux/macOS use their corresponding versioned binary in .local/bin.
& ./.local/bin/kind-v0.33.0-windows-amd64.exe delete cluster --name csc3104 --kubeconfig .local/k8s/kubeconfig
python demo.py --kubernetes --verify
```

Deleting an initialized cluster destroys its node-local database and Redis data.
Normal restart and `--stop` preserve them.

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
python infra/k8s/kubectl.py -n csc3104 get 'pods,pvc,services,jobs'
python infra/k8s/kubectl.py -n csc3104 exec deployment/payment-worker -- python service.py monitor
python infra/k8s/kubectl.py -n csc3104 logs deployment/allocation-worker --tail=50
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
