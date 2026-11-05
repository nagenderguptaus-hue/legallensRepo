# Backend CI: merge gate for `main`

> **Status:** ✅ implemented 2026-10-29 in `.github/workflows/backend-ci.yml` (green signal given).
> Verified locally; not yet run on GitHub (no remote). Not committed.
> **Scope:** a GitHub Actions merge gate for the backend. CD comes later.

## 1. Facts from the repo (checked, not guessed)

| Item | Value | Source |
|---|---|---|
| Local baseline | ruff format ✅, ruff check ✅, mypy strict ✅ (68 files), pytest 115 passed, 1 deselected (live), 28 s | run 2026-10-29 |
| Test layout | `tests/unit` (44), `tests/contract`, `tests/integration`, `tests/live` (deselected, real Anthropic API) | `backend/tests/` |
| Coverage gate | `--cov-fail-under=85`, branch coverage | `backend/pyproject.toml` |
| Existing CI | `.github/workflows/backend.yml` already runs lint, types, tests and a Docker smoke test on **every push and PR**, on Ubuntu, Windows and macOS, filtered by path | `.github/workflows/backend.yml` |
| Branches | `main` exists; you are on `ingestion` with uncommitted work | `git branch -a`, `git status` |
| Git remote | **none configured**. GitHub can't run any workflow until the repo is pushed | `git remote -v` (empty) |

## 2. Questions (recommendation first)

1. **Which workflow owns the merge gate?**
   - **(Recommended)** A new `backend-ci.yml` that runs only for PRs into `main` and pushes to `main`. Leave `backend.yml` for branch feedback.
   - Alternative: change the triggers in `backend.yml` instead. That makes one file, but it mixes the gate with branch feedback.
2. **What counts as "unit tests" for the gate?**
   - **(Recommended)** All offline tests: `tests/unit`, `tests/contract` and `tests/integration`, excluding `live`. They take about 28 s, need no API key, and are the only tests that cover the real request flow.
   - Alternative: `tests/unit` only, about 1 s, but misses the integration coverage.
3. **Which OS runs the required check?**
   - **(Recommended)** Ubuntu for the required check. It is fast and cheap. Windows, your laptop, runs as a second job because the portability goal requires it. macOS stays in `backend.yml`.
   - Alternative: all three OSes required. Slower, and more minutes spent.
4. **Docker smoke test in the gate?**
   - **(Recommended)** Yes, plain image only (`LL_EXTRAS=""`). The AI image (about 1 GB, many minutes) stays in `backend.yml`.
   - Alternative: skip Docker in the gate. Faster, but a broken Dockerfile can then reach `main`.
5. **Which extras are installed in the gate?**
   - **(Recommended)** `uv sync --locked --extra ai`, as `backend.yml` does. The AI ingestion tests then run instead of being skipped. It is heavier to install (onnxruntime, rapidocr).
   - Alternative: no extras. Faster, but the AI ingestion adapter is not type-checked or tested on merge.
6. **"Build the CI .html files": what do you mean?**
   - **(Recommended)** Two self-contained HTML reports, uploaded as workflow artifacts for 30 days: a **pytest HTML report** (`pytest-html`, new dev dependency) and a **coverage HTML report** (`coverage html`). Open them from the run's Artifacts section.
   - Alternative: publish them on GitHub Pages so they are viewable from a link. That needs a public Pages setup, which is a decision for later.
7. **Required check enforcement** (cannot be done from files):
   - **(Recommended)** After the first green run, add a branch protection rule (or ruleset) on `main` that requires the `backend-ci` checks and blocks direct pushes. You do this in GitHub Settings. I can give you the exact steps, or run `gh api` if you want me to.

## 3. Phases (after approval)

1. **Workflow file.** Create `.github/workflows/backend-ci.yml`.
   - Triggers: `pull_request` and `push`, both only for `branches: [main]`. No path filter, because a path-filtered required check never reports on unrelated PRs and blocks them.
   - `concurrency` cancels superseded runs.
   - Jobs: `quality` (format, ruff, mypy) and `tests` (pytest with `--html` and `--cov-report=html`, coverage gate 85), plus `docker` (build and health smoke test).
   - Each run uploads `reports/` as an artifact.
2. **Dependency.** Add `pytest-html` to the backend `dev` group and re-lock `backend/uv.lock` (`uv lock`).
3. **Local verification.** Run the exact commands the workflow runs, from the `backend` folder, and check the HTML files are produced and open.
4. **Static check of the YAML.** Parse it and check that every command matches step 3. I can't run GitHub Actions locally, so the first real proof is the first run after the repo is on GitHub.

## 4. Deviations and known gaps

- I cannot run GitHub-hosted runners here. Until the repo has a GitHub remote and the first run passes, the workflow is verified only by local commands.
- `backend.yml` will still run its own checks on every branch. This duplicates the Ubuntu quality job. If you want to avoid the extra minutes, I can narrow `backend.yml` to non-`main` branches later.
- Your current work is uncommitted on `ingestion`. The gate only sees what is committed and merged into `main`.
