# Legal Lens: deploying to AKS (CD plan)

> **Status:** the pipeline is written (`.github/workflows/cd.yml`, `deploy/k8s/`) but has not run against Azure yet. Before the first run, do the one-time identity setup with `bash deploy/setup-cd.sh`, which creates no passwords. This file does not create Azure resources.
> **Audience:** the instructor, and students who repeat this after the class.
> **Scope:** the smallest working deployment on Azure Kubernetes Service (AKS). It is not production-ready: no HTTPS, no custom domain, no autoscaling, no monitoring, no backups.

---

## 1. What runs in AKS

The repo already builds two Docker images (see [backend/Dockerfile](backend/Dockerfile) and [frontend/Dockerfile](frontend/Dockerfile), and the wiring in [compose.yaml](compose.yaml)):

| Image | Build context | Listens on | Notes |
|---|---|---|---|
| `legallens-backend` | repository root (`.`), file `backend/Dockerfile` | `8000` | Health check: `/api/health/ready`. Writes SQLite and uploads to `/data`. |
| `legallens-frontend` | `frontend/` | `8080` | nginx serves the UI and proxies `/api` to the backend through `BACKEND_URL`. |

**Constraints that shape the plan:**
- The backend keeps its data in SQLite and an embedded vector index under `/data`. Run **one** backend replica, with a persistent volume.
- The frontend's `BACKEND_URL` must point to the backend's Kubernetes Service. Use the full name, for example `http://backend.legallens.svc.cluster.local:8000`.
- The AI image (optional) needs an `ANTHROPIC_API_KEY`. Store it as a Kubernetes Secret, never in the image or in Git.

---

## 2. Resources you need

| # | Resource | Example name | Created in step | Why |
|---|---|---|---|---|
| 1 | Azure account and subscription | (yours) | 1 | Everything is billed to a subscription |
| 2 | Resource group | `rg-legallens-dev` | 2 | Holds every other Azure resource. Delete it to delete all of them. |
| 3 | Azure Container Registry (ACR), Basic tier | `acrlegallens7kq2` (must be globally unique) | 3 | Stores the two images. AKS pulls from it. |
| 4 | AKS cluster, 1 node | `aks-legallens-dev` | 4 | Runs the containers |
| 5 | Managed disk (created automatically) | (in the node resource group `MC_...`) | 6 | Persistent `/data` for the backend. AKS creates it from a PersistentVolumeClaim. |
| 6 | Kubernetes objects (manifests, written in a later step) | namespace `legallens` | 6 | Deployments, Services, Secret, PersistentVolumeClaim |

**Local tools** (on your own computer, not in Azure):

- Azure CLI (`az`). Check with `az --version`.
- `kubectl`. Install it with `az aks install-cli`, or it comes with Docker Desktop.
- Docker Desktop, to build and push images.

**Naming rules:** resource group names may contain letters, digits, `-`, `_`, `.`, `()`. ACR names must be globally unique, 5 to 50 characters, lowercase letters and digits only. AKS names may contain letters, digits and `-`.

---

## 3. To-do list

- [ ] **Phase 0: local tools** installed and working (Azure CLI, kubectl, Docker Desktop). See section 4.
- [ ] **Phase 1: Azure account.** Create a free account or use your school's subscription.
- [ ] **Phase 2: resource group.** Create `rg-legallens-dev`.
- [ ] **Phase 3: Azure Container Registry.** Create the ACR.
- [ ] **Phase 4: AKS cluster.** Create the cluster and connect it to the ACR.
- [ ] **Phase 5: push the images.** Build both images for `linux/amd64` and push them to the ACR.
- [ ] **Phase 6: Kubernetes objects.** Write the manifests and deploy (planned after the answers in section 6).
- [ ] **Phase 7: check the app.** Open the UI and run the demo seed.
- [ ] **Phase 8: clean up.** Delete the resource group so billing stops.

---

## 4. Step by step

Each resource has two methods: **CMD** (Azure CLI in Windows Command Prompt) and **Web interface** (the Azure portal at https://portal.azure.com). Both do the same thing. You can use either one.

### Phase 0: local tools

**CMD**

```bat
az --version
kubectl version --client
docker --version
az login
```

`az login` opens a browser window to sign in.

**Web interface:** install Azure CLI from https://learn.microsoft.com/cli/azure/install-azure-cli and Docker Desktop from https://www.docker.com/products/docker-desktop. The portal needs no tools.

**Variables for the CMD steps.** Run these in the same Command Prompt window before the other CMD steps. A new window needs them again. Change `ACR_NAME` to a name nobody else uses.

```bat
set RG=rg-legallens-dev
set LOCATION=eastus
set ACR_NAME=acrlegallens7kq2
set AKS_NAME=aks-legallens-dev
```

### Phase 1: Azure account

**CMD:** an account has to exist before `az login` works. Create one, then sign in with it.

**Web interface**
1. Go to https://azure.microsoft.com/free and choose the free account. It includes trial credit for a limited time (check the current terms).
2. Sign in at https://portal.azure.com.
3. Open **Subscriptions** and note the subscription name. Creating the AKS cluster requires the Owner role, or the User Access Administrator role, on the subscription. Otherwise the attach-ACR step fails.

### Phase 2: resource group

**CMD**

```bat
az account show --query name -o tsv
az group create --name %RG% --location %LOCATION%
```

**Web interface**
1. In the portal search bar, type **Resource groups**, then select **+ Create**.
2. Subscription: your subscription. Resource group: `rg-legallens-dev`. Region: `East US` (or the region you chose).
3. Select **Review + create**, then **Create**.

### Phase 3: Azure Container Registry (ACR)

**CMD**

```bat
az acr create --resource-group %RG% --name %ACR_NAME% --sku Basic
az acr list --resource-group %RG% -o table
```

**Web interface**
1. Search for **Container registries**, then select **+ Create**.
2. Subscription and resource group: `rg-legallens-dev`. Registry name: `acrlegallens7kq2` (yours). Location: same as the resource group. Pricing plan: **Basic**.
3. Select **Review + create**, then **Create**.

### Phase 4: AKS cluster

**CMD**

```bat
az aks create --resource-group %RG% --name %AKS_NAME% --location %LOCATION% --node-count 1 --node-vm-size Standard_D2s_v3 --generate-ssh-keys --attach-acr %ACR_NAME%
az aks get-credentials --resource-group %RG% --name %AKS_NAME%
kubectl get nodes
```

`--attach-acr` lets the cluster pull images from the registry without a password. `kubectl get nodes` should show one node in `Ready` state. The cluster creation takes several minutes.

**Web interface**
1. Search for **Kubernetes services**, then select **+ Create** → **Create a Kubernetes cluster**.
2. **Basics:** subscription and resource group `rg-legallens-dev`. Cluster name `aks-legallens-dev`. Region: same as before. Availability zones: **None**. Node size: `Standard_D2s_v3`.
3. **Node pools:** node count `1`. Turn off autoscaling.
4. **Integrations:** Container registry: `acrlegallens7kq2`.
5. Select **Review + create**, then **Create**. Wait for the deployment to finish, then open the cluster and select **Connect** to see the `az aks get-credentials` command.

### Phase 5: push the images to ACR

Run these from the `LegalLens` folder (the repository root). AKS nodes are `linux/amd64`, so build with `--platform linux/amd64`. This matters on Apple Silicon Macs and other ARM machines.

**CMD**

```bat
az acr login --name %ACR_NAME%
docker build --platform linux/amd64 -f backend/Dockerfile -t %ACR_NAME%.azurecr.io/legallens-backend:0.1.0 .
docker build --platform linux/amd64 -f frontend/Dockerfile -t %ACR_NAME%.azurecr.io/legallens-frontend:0.1.0 frontend
docker push %ACR_NAME%.azurecr.io/legallens-backend:0.1.0
docker push %ACR_NAME%.azurecr.io/legallens-frontend:0.1.0
az acr repository list --name %ACR_NAME% -o table
```

*Without local Docker:* `az acr build --registry %ACR_NAME% --image legallens-backend:0.1.0 --file backend/Dockerfile .` (and the same for the frontend, with `frontend` as the last argument). Azure builds the image in the cloud. I have not tested this path for this repo.

**Web interface:** the portal cannot push images. You can check the result: open the registry, then **Repositories**. Both `legallens-backend` and `legallens-frontend` should appear with the tag `0.1.0`.

### Phase 6: Kubernetes objects (planned, not written yet)

These are the objects the next step will create. I have not written them. Each one is a manifest or a command you run against the cluster.

| Object | Purpose |
|---|---|
| Namespace `legallens` | Keeps the app's objects together |
| Secret `legallens-secrets` | Holds `ANTHROPIC_API_KEY`, only if you use the AI image |
| PersistentVolumeClaim `legallens-data` | 1 to 5 GB, for backend `/data`. AKS creates the Azure managed disk. |
| Deployment `backend` | 1 replica, strategy **Recreate** (a disk can't attach to two pods during a rolling update) |
| Service `backend` (ClusterIP, port 8000) | Lets the frontend reach the backend |
| Deployment `frontend` | 1 replica, `BACKEND_URL` set to the backend Service's full name |
| Service `frontend` | Makes the UI reachable from your computer (see question 3) |

Web interface for this phase: the portal can view these objects under the cluster's **Resources** and **Workloads** pages, but creating them is done with `kubectl` (CMD) in this plan.

### Phase 7: check the app

**CMD**

```bat
kubectl get pods -n legallens
kubectl port-forward -n legallens svc/frontend 8080:8080
```

Then open http://127.0.0.1:8080 in your browser. `port-forward` keeps the app private: only your computer can reach it. To load the demo data, run `uv run python scripts/seed_demo.py --url http://127.0.0.1:8080` from the `backend` folder (the same script as the local Docker stack, see [backend/README.md](backend/README.md)).

**Web interface:** in the cluster, open **Workloads** → **Pods**. Each pod should show `Running` and `1/1` ready.

### Phase 8: clean up

Everything is billed while it exists. Deleting the resource group removes the cluster, the registry, the disk and the public IP (if any) together.

**CMD**

```bat
az group delete --name %RG% --yes --no-wait
```

**Web interface:** open **Resource groups**, select `rg-legallens-dev`, then **Delete resource group**. Type the name to confirm.

---

## 5. Things to know

- **Costs.** The AKS node, the registry and any public IP are billed. Check the current prices in the Azure pricing calculator before you leave resources running.
- **Single backend replica.** SQLite and the vector index allow only one writer, so do not scale the backend beyond 1 replica.
- **Secrets.** Never put `ANTHROPIC_API_KEY` in an image, a manifest in Git, or `CD_readme.md`.
- **Image tags.** `0.1.0` is fixed for now. Later, the CD pipeline should tag images with the Git commit.
- **Not included.** HTTPS, a custom domain, an Application Gateway or ingress controller, monitoring, backups, and autoscaling. The automated deploy is in section 7.

---

## 6. Questions before we continue

1. **Region.** I used `eastus`. Which region should the class use? Pick one close to you and the students.
2. **Node size.** `Standard_D2s_v3` (2 vCPU, 8 GB RAM) is enough for the stand-in backend. Do you also want the AI image, which downloads about 3.6 GB of models? If so, the node needs more memory. **Recommendation:** start with the stand-in image, then add the AI image.
3. **How the class reaches the app.**
   - **(Recommended)** `kubectl port-forward`. Nothing is public. The app has no login, and the requirements say documents stay on the local machine (NFR-5), so a public address is a risk.
   - Alternative: a public `LoadBalancer` IP for the frontend. Anyone who finds the IP can upload documents. Only use this with an IP allow-list.
4. **Build method.** Do students have Docker Desktop installed? If not, the `az acr build` path avoids it, but I have not tested it yet.
5. **Ingress and HTTPS.** Skip for now (my recommendation), or add them in a later phase?

The answers used for the automated deploy: region and names as in section 4, the stand-in backend image, the private frontend (`port-forward`), and no ingress.

---

## 7. Automated deploy (CD)

**What it does.** After `backend-ci` passes on `main`, the workflow [.github/workflows/cd.yml](.github/workflows/cd.yml):

1. Takes the backend image that CI built and smoke-tested (the same bytes, not a rebuild).
2. Builds the frontend image from the same commit.
3. Pushes both to ACR, tagged with the commit SHA and `latest`.
4. Applies the manifests in [deploy/k8s/](deploy/k8s/) with `kubectl apply -k`, using the SHA tags.
5. Waits for both rollouts, then checks `/api/health/ready` through the frontend's proxy.

You can also start it by hand: **Actions → cd → Run workflow**. That deploys the newest green `backend-ci` run on `main`.

**Login.** GitHub logs in to Azure with OIDC, so no password is stored in GitHub. Run this once, in Git Bash, after `az login` and `gh auth login`:

```bash
REPO=nagenderguptaus-hue/legallensRepo
RG=rg-legallens-dev
ACR_NAME=acrlegallens7kq2
AKS_NAME=aks-legallens-dev

SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

# The identity GitHub uses
APP_ID=$(az ad app create --display-name github-legallens-cd --query appId -o tsv)
az ad sp create --id "$APP_ID"

# Trust GitHub: the main branch (publish job) and the dev environment (deploy job)
az ad app federated-credential create --id "$APP_ID" --parameters \
  "{\"name\":\"github-main\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"repo:$REPO:ref:refs/heads/main\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
az ad app federated-credential create --id "$APP_ID" --parameters \
  "{\"name\":\"github-env-dev\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"repo:$REPO:environment:dev\",\"audiences\":[\"api://AzureADTokenExchange\"]}"

# Permissions: push to ACR, and fetch the cluster credentials
az role assignment create --assignee "$APP_ID" --role AcrPush \
  --scope "$(az acr show -g $RG -n $ACR_NAME --query id -o tsv)"
az role assignment create --assignee "$APP_ID" --role "Azure Kubernetes Service Cluster User Role" \
  --scope "$(az aks show -g $RG -n $AKS_NAME --query id -o tsv)"

# GitHub: the dev environment, and the variables cd.yml reads (variables, not secrets)
gh api -X PUT "repos/$REPO/environments/dev"
gh variable set AZURE_CLIENT_ID --body "$APP_ID" --repo "$REPO"
gh variable set AZURE_TENANT_ID --body "$TENANT_ID" --repo "$REPO"
gh variable set AZURE_SUBSCRIPTION_ID --body "$SUB_ID" --repo "$REPO"
gh variable set ACR_NAME --body "$ACR_NAME" --repo "$REPO"
gh variable set AKS_NAME --body "$AKS_NAME" --repo "$REPO"
gh variable set AZURE_RESOURCE_GROUP --body "$RG" --repo "$REPO"
```

**Deviation from the plan (cd.todo.md, question 3).** The cluster has no Entra ID integration (`CD_readme.md`, phase 4 has no `--enable-aad`), so the `Azure Kubernetes Service RBAC Writer` role does not apply. The identity gets `Cluster User Role`, which lets it fetch the kubeconfig. On a cluster without Entra ID, that kubeconfig carries full cluster-admin rights. This is acceptable for the class. To narrow it later, enable Entra ID and Azure RBAC on the cluster, then switch to the RBAC Writer role.

**First run.** `cd.yml` only runs from `main`, so push the workflow files first. Then, with `backend-ci` green on `main`, check the **cd** run in the Actions tab. Each step's log says what happened.

**Check the app** (unchanged from phase 7): `kubectl port-forward -n legallens svc/frontend 8080:8080`, then open http://127.0.0.1:8080.
