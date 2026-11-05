# Legal Lens: CD pipeline to AKS (plan)

> **Status:** implemented (`cd.yml`, `deploy/k8s/`, `deploy/setup-cd.sh`). Section 1 below is the state before implementation: CI now saves the image on `main`, and a frontend image is built by `cd.yml`. Not yet run against Azure.
> **Builds on:** [CD_readme.md](CD_readme.md) (the manual AKS setup you already did, phases 0-5), [backend/docker.todo.md](backend/docker.todo.md) (health probes, image), [backend/ci.todo.md](backend/ci.todo.md) (the merge gate).
> **Scope:** `.github/workflows/cd.yml` that takes the backend image built by CI, pushes it to ACR, and deploys backend and frontend to AKS. Not in scope: HTTPS, domain, ingress, monitoring, backups, autoscaling, the AI image.

## 1. Facts from the repo (checked, not guessed)

| Item | Value | Source |
|---|---|---|
| "ci.yml" | There is no file with that name. The CI gate is `.github/workflows/backend-ci.yml`. I treat it as the CI you mean. | `.github/workflows/` |
| What CI builds today | `backend-ci.yml` job `docker` builds `legallens-backend` (stand-in image, `LL_EXTRAS=""`), runs it, checks `/api/health/ready`, then throws it away. | `backend-ci.yml` lines 72-94 |
| Does anything push an image? | **No.** No workflow logs in to Azure or ACR, and no workflow has Azure secrets. | all of `.github/workflows/` |
| Frontend image in CI | **Never built** by CI. Only `integration.yml` builds it, through Compose, and does not keep it. | `integration.yml` |
| Git remote | Now set: `https://github.com/nagenderguptaus-hue/legallensRepo.git`. (`ci.todo.md` said none; that is out of date.) | `git remote -v` |
| Health probes | `GET /api/health/live` (process is up) and `GET /api/health/ready` (503 until ready). | `backend/docker.todo.md` G2 |
| Backend state | SQLite, uploads and index under `/data`. One process, one writer, so **one replica** with a persistent volume. | `backend/Dockerfile` |
| Backend user | uid `10001` (numeric, so `runAsNonRoot` can be verified). | `backend/Dockerfile` |
| Frontend | nginx on `8080`, runs as uid `101`, proxies `/api/` to `BACKEND_URL`. The name must be the full cluster DNS name, because nginx does not use search domains. | `frontend/Dockerfile`, `frontend/nginx.conf.template` |
| Config | Everything comes from `LL_*` variables. The stand-in image needs no secret. | `backend/.env.docker.example` |

**The gap in one line:** the image CI builds is discarded, so CD has no image to take. CD needs CI to hand the image over, or CD has to build it again.

## 2. Questions (recommendation first)

**Q1. How does CD get the image CI built?**
- **(Recommended)** Change `backend-ci.yml`'s `docker` job so that on push to `main` it saves the image it built (`docker save`, gzip) as a workflow artifact. `cd.yml` downloads that exact image, loads it, and pushes it to ACR. This is the same image bytes CI tested. It needs one small change to `backend-ci.yml`, which is outside `cd.yml`.
- Alternative: `cd.yml` rebuilds from the same commit. No CI change, but the pushed image is a rebuild, not the one CI tested.
- Alternative: CI pushes to ACR itself. Simplest, but then CD only deploys.

**Q2. Which tags?**
- **(Recommended)** Push two tags per build: the **git commit SHA** (never changes) and `latest` (moves). CD **deploys the SHA**. The SHA of the newest commit on `main` is the latest build, and the cluster can then say which commit is running and roll back to a named build.
- Alternative: deploy `latest`, as you wrote. It works, but nothing in the cluster records which build is running, and a rollback has no name to go back to.

**Q3. How does GitHub log in to Azure?**
- **(Recommended)** OIDC (federated credential). No password stored in GitHub. You run a one-time setup in Phase 0. Roles: `AcrPush` on the ACR, and `Azure Kubernetes Service RBAC Writer` on the AKS cluster.
- Alternative: a service principal secret stored in GitHub. Simpler to set up, but a long-lived secret that must be rotated.

**Q4. When does CD run?**
- **(Recommended)** Automatically after `backend-ci` passes on `main`, and also by a manual "Run workflow" button. Deploys go to a GitHub environment named `dev`, which can be given required reviewers later.
- Alternative: manual button only.

**Q5. Manifests: Kustomize or Helm?**
- **(Recommended)** Plain YAML with **Kustomize** (built into `kubectl`, `kubectl apply -k`). Two apps, one environment, so nothing needs templating. CD sets the image tag with Kustomize's `images:` field.
- Alternative: a Helm chart. Worth it when you have several environments (dev, prod) or want versioned releases. Not needed for this project yet, so I would not add it now.

**Confirm these (no alternatives, they are needed for the workflow):**
- Names you created: resource group `rg-legallens-dev`, region `eastus`, ACR `acrlegallens7kq2`, AKS `aks-legallens-dev`, namespace `legallens`. The workflow reads these as GitHub variables. Tell me if any name differs.
- Image: stand-in backend (`LL_EXTRAS=""`), 309 MB, no secret, no model download. The AI image comes in a later phase.
- Access: the frontend stays private (`ClusterIP` plus `kubectl port-forward`), as `CD_readme.md` recommends.

## 3. Phases (after approval)

**Phase 0. One-time Azure and GitHub setup (you run it, I write the exact commands).**
- Create an Entra app registration with a federated credential for this repo (`main` branch and the `dev` environment).
- Assign `AcrPush` on the ACR, and `Azure Kubernetes Service RBAC Writer` on the cluster's namespace or cluster. Role assignments can take a few minutes to take effect.
- Set GitHub repository **variables** (not secrets; OIDC needs none): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `AKS_NAME`, `AZURE_RESOURCE_GROUP`.

**Phase 1. Kubernetes manifests in `LegalLens/deploy/k8s/` (Kustomize).**
- `namespace.yaml`: namespace `legallens`.
- `backend.yaml`:
  - PersistentVolumeClaim `legallens-data`: 5 Gi, `ReadWriteOnce`, storage class `managed-csi`.
  - Deployment `backend`: 1 replica, strategy `Recreate` (the disk can't attach to two pods during a rolling update). Non-root (uid 10001). Liveness on `/api/health/live`, readiness on `/api/health/ready`. Env from a ConfigMap: `LL_INGESTION=standin`, `LL_ORCHESTRATOR=standin`, `LL_DATA_DIR=/data`, `LL_LOG_JSON=true`. Requests and limits set.
  - Service `backend`: ClusterIP, port 8000.
- `frontend.yaml`:
  - Deployment `frontend`: 1 replica, `RollingUpdate`. Non-root (uid 101). `BACKEND_URL=http://backend.legallens.svc.cluster.local:8000`. Probe on `/healthz`.
  - Service `frontend`: ClusterIP, port 8080.
- `kustomization.yaml`: lists the files, and an `images:` entry for each image whose tag CD replaces.
- **Check:** whether the backend runs Alembic migrations at startup. If not, the plan adds a migration step before the rollout.

**Phase 2. Image hand-over.**
- Per Q1: change `backend-ci.yml`'s `docker` job to save the image as an artifact on `main` only.
- Frontend image: `cd.yml` builds it, since CI has no frontend image yet. Built `--platform linux/amd64`, the same as CD_readme.

**Phase 3. `.github/workflows/cd.yml`.**
- Triggers: `workflow_run` on `backend-ci` (branch `main`, conclusion `success`), and `workflow_dispatch`.
- `concurrency: cd-dev`, `cancel-in-progress: false`, so two deploys never overlap.
- Job `publish`:
  1. Download the backend image artifact (Q1), `docker load`, retag.
  2. Build the frontend image (`linux/amd64`).
  3. Azure login with OIDC, then `az acr login`.
  4. Push both images, tagged with the commit SHA and `latest`.
- Job `deploy` (environment `dev`):
  1. Azure login, then `azure/aks-set-context`.
  2. Set the image tags to the SHA with Kustomize, then `kubectl apply -k`.
  3. `kubectl rollout status` for backend and frontend, with a timeout.
  4. Smoke test through the frontend's own proxy: `kubectl exec deploy/frontend -- wget -qO- http://127.0.0.1:8080/api/health/ready`. This proves nginx, the Service DNS name and the backend all work together.
- Rollback: if the rollout fails, the job fails loudly. Going back to an earlier build means re-running `cd.yml` with that SHA. This is a manual step; no automatic rollback is planned.

**Phase 4. Verify what I can.**
- `kubectl kustomize` renders the manifests with no error.
- `kubectl apply --dry-run=server` against your cluster (needs your kube context on this machine).
- Lint the workflow with `actionlint`.
- **Not verifiable here:** GitHub runners and the real AKS rollout. The first real proof is a manual "Run workflow" run after the repo is pushed with the new files. I will say so when I report back.

**Phase 5. Documentation.**
- Add a "CI/CD (GitHub Actions)" section to `CD_readme.md`, and mark phase 6 done in `CD_readme.md` once the manifests are in place.
- Record the results and any deviations here in section 6.

## 4. Not in scope (later)

HTTPS and ingress, a custom domain, monitoring, backups, autoscaling, the AI image (needs an `ANTHROPIC_API_KEY` secret and a larger node), and the demo seed (still manual, as in `CD_readme.md` phase 7).

## 5. Risks

- `Recreate` causes a short backend outage on every deploy. Acceptable for a class demo.
- Role assignments can take minutes to apply, so the first `publish` can fail on auth even when the setup is correct.
- Only one replica can run, so a deploy can never be zero-downtime for the backend.
- Nothing here has run on GitHub or on AKS yet (see Phase 4).

## 6. Results and deviations

**Approved answers:** Q1 CI hands the image over (recommended). Q2 SHA tag, deploy by SHA. Q3 OIDC. Q4 automatic after CI plus a manual button. Q5 plain YAML with Kustomize.

**Built (not committed):**
- `.github/workflows/backend-ci.yml`: on push to `main`, the `docker` job saves the tested image and uploads it as the artifact `backend-image` (7 days).
- `.github/workflows/cd.yml`: `publish` job (the image from the green CI run, frontend build, push SHA + `latest` to ACR) and `deploy` job (environment `dev`, `kubectl apply -k`, rollout wait, smoke test through the frontend proxy).
- `deploy/k8s/`: namespace, backend (PVC 5 Gi `managed-csi`, `Recreate`, one replica, non-root uid 10001 with `fsGroup`, probes on `/api/health/live` and `/api/health/ready`), frontend (non-root uid 101, `BACKEND_URL` full DNS name, probe `/healthz`), `kustomization.yaml`.
- `CD_readme.md`, section 7: setup commands and the first-run notes.

**Checked locally:** `kubectl kustomize` renders 7 objects; the image tag rewrite works on a copy; both workflows parse as YAML. Not checked: `actionlint` (not installed), server-side dry-run (no kubeconfig here), GitHub runners, AKS.

**Deviations:**
- Role: `Cluster User Role` instead of `RBAC Writer`. The cluster has no Entra ID, so RBAC Writer doesn't apply. The identity is cluster-admin in effect (see CD_readme section 7).
- Migrations: no extra step. The backend runs `alembic upgrade head` at startup (`backend/src/legallens/db/engine.py`).
- The resource names in the workflow come from GitHub variables, not hard-coded. You have not confirmed them yet; the variables in CD_readme section 7 must match what you created.

**Still to do by you:** run the Phase 0 commands in CD_readme section 7, push the files to `main`, then check the first `cd` run.

## 7. Status

Approved and built. Not committed or pushed. The first real test is the first run on GitHub.
