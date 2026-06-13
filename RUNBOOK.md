# Lead Scraper — Operator Runbook

How to host, onboard, update, back up, and offboard single-tenant client
instances of the Lead Scraper. One private repo is the single source of truth;
the code is byte-identical across all clients, and **only per-client secrets
differ**. Clients receive only a URL + login — never the repo, image, or source.

Target host: **Render** (Docker service + persistent disk + automatic HTTPS).
The rollout/rollback/backup scripts are host-agnostic except for one swappable
deploy function (see [`deploy/rollout.sh`](deploy/rollout.sh)).

---

## 0. Concepts

| Thing | Where it lives |
|---|---|
| Application code | This repo. Identical for every client. |
| The image | Built from the [`Dockerfile`](Dockerfile). No secrets baked in. |
| Per-client secrets | `secrets.toml` → base64 → the `SECRETS_TOML_B64` env var on that instance. Never committed. |
| Per-client data | `leads.db` on that instance's **persistent disk**. Never in the image. |
| Per-instance rollout config | `deploy/instances/<instance>.env` (service id + URL; not secret, git-ignored). |

The image reads two things at runtime:
- **Top-level keys** (`GOOGLE_PLACES_API_KEY`, `ANTHROPIC_API_KEY`, `COOKIE_KEY`,
  `COOKIE_NAME`, `CLIENT_NAME`) — bridged from `secrets.toml` into the
  environment by `app.py`.
- **The `[auth.users.*]` login table** — read straight from `secrets.toml` by
  `config.py`.
- **`LEADS_DB_PATH`** — set as a plain (non-secret) env var pointing at the
  database file on the mounted disk.

---

## 1. Prerequisites (one time)

- A Render account you control (the operator owns all hosting).
- A Render API key with deploy permission → export locally as `RENDER_API_KEY`
  (never commit it).
- Docker installed locally (only needed to verify the image before release).
- `git`, `bash`, `curl`, and ideally `sqlite3` on the operator machine.

---

## 2. Onboard a new client

A repeatable "new client in N minutes" sequence.

### 2.1 Create the instance
1. In Render, create a new **Web Service** from this repo, runtime **Docker**.
2. Attach a **persistent disk** (e.g. mount path `/var/data`).
3. Set a plain env var `LEADS_DB_PATH=/var/data/leads.db` so the database lives
   on the disk (not ephemeral container storage).
4. Render provides HTTPS automatically.
5. **Turn auto-deploy OFF** (Settings → Build & Deploy → Auto-Deploy: **No**).
   Client instances must update only through the staged rollout (§3) with a
   verified tag — never automatically on every push to `main`. This is the D5
   "staged, never push-to-all" rule: a bad commit must not reach every client at
   once. (A staging/canary instance that intentionally tracks `main` may leave
   auto-deploy on; client instances must not.)

### 2.2 Build the client's secrets
Create a `secrets.toml` from [`secrets.toml.example`](secrets.toml.example):
- `GOOGLE_PLACES_API_KEY`, `ANTHROPIC_API_KEY` — the client brings their own.
- `COOKIE_KEY` — freshly random, unique per instance:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- `COOKIE_NAME` — unique per client (so cookies never collide across instances).
- `CLIENT_NAME` — the client's display name.
- One `[auth.users.<username>]` block per user. Generate each password hash:
  ```bash
  python gen_password_hash.py        # prompts; paste the printed hash
  ```

### 2.3 Deliver the secrets into the instance
Base64-encode the finished file and set it as a **secret** env var on the
instance:
```bash
base64 -w0 secrets.toml      # Linux/Git-Bash;  use `base64 -i secrets.toml` on macOS
```
Set the output as `SECRETS_TOML_B64` in the Render service's environment. Do
**not** commit `secrets.toml` or the encoded value. The container's entrypoint
decodes it to `.streamlit/secrets.toml` (mode 600) at startup and never logs it.

### 2.4 Register the instance for rollouts
Create `deploy/instances/<instance>.env` (git-ignored) from
[`deploy/instances/example.env`](deploy/instances/example.env):
```
RENDER_SERVICE_ID=srv-...
HEALTHCHECK_URL=https://<client>-leads.onrender.com
```

### 2.5 Deploy + smoke test
Deploy the current released tag (see §3), then confirm:
- [ ] HTTPS loads.
- [ ] The login gate blocks an unauthenticated session.
- [ ] A valid login works.
- [ ] A search returns results.
- [ ] Save + the **My Leads** view work.

### 2.6 Hand off
Give the client **only** the URL and their credentials.

---

## 3. Release & rollout (staged, never push-to-all)

Updates improve the product for everyone, but a bad commit must never break
every client at once.

1. **Tag a release** from `main`:
   ```bash
   git tag -a v1.3.0 -m "..." && git push origin v1.3.0
   ```
2. **Deploy to your staging/canary instance first** (an instance you own,
   configured like a real client) and verify it there:
   ```bash
   export RENDER_API_KEY=rnd_...
   bash deploy/rollout.sh deploy v1.3.0 staging
   ```
   The script resolves the tag to a commit, triggers a deploy of that commit,
   waits for it to go live, then runs a health check against
   `<HEALTHCHECK_URL>/_stcore/health`. It records the deploy so rollback knows
   the prior good version.
3. **Promote the verified tag to each client, one at a time:**
   ```bash
   bash deploy/rollout.sh deploy v1.3.0 acme
   bash deploy/rollout.sh deploy v1.3.0 globex
   ```
   List configured instances with `bash deploy/rollout.sh list-instances`.
4. Keep the previous tag deployable for fast rollback (below).

### Rollback
Redeploy the instance's previous recorded-good tag:
```bash
bash deploy/rollout.sh rollback acme
```

### Check health
```bash
bash deploy/rollout.sh status acme
```

> Retargeting another host: swap `trigger_deploy()` and `deploy_status()` in
> [`deploy/rollout.sh`](deploy/rollout.sh); the rest (tag resolution, polling,
> health check, history/rollback) is host-agnostic.

---

## 4. Backups (per instance)

Each client's saved leads/status/notes are the client's data and are protected
independently of the code. Run [`deploy/backup.sh`](deploy/backup.sh) on a
schedule against the database on the mounted disk:
```bash
bash deploy/backup.sh /var/data/leads.db /var/backups
# -> /var/backups/leads_20260612T143000Z.db
```
It makes a consistent snapshot via `sqlite3 .backup` (falling back to `cp`).
Wire it to a scheduled job (e.g. a Render Cron Job with access to the disk) and
copy the output to off-instance storage (object storage) for durability.

---

## 5. Offboarding (disable, do not delete)

To offboard a client:
1. **Disable** the instance (suspend the Render service) — the kill switch.
2. **Revoke** the client's login (remove their `[auth.users.*]` entry / rotate
   `SECRETS_TOML_B64`, or suspend the service).

Do **not** hard-delete the client's data as part of offboarding.
Retention/disposal is a contract matter handled separately; keep the latest
backup until that's settled.

---

## 6. Verify the image locally (before a release)

Requires Docker. See the acceptance checklist in
[`BRIEF_deployment_and_updates.md`](BRIEF_deployment_and_updates.md). Quick pass:

```bash
# 1. Build
docker build -t lead-scraper:dev .

# 2. Fails clearly with NO secrets
docker run --rm -p 8501:8501 lead-scraper:dev          # should exit non-zero, log FATAL

# 3. Runs with runtime secrets on a persistent volume
docker volume create ls_data
B64=$(base64 -w0 secrets.toml)
docker run --rm -p 8501:8501 \
  -e SECRETS_TOML_B64="$B64" \
  -e LEADS_DB_PATH=/var/data/leads.db \
  -v ls_data:/var/data \
  lead-scraper:dev
# open https://localhost:8501 -> login gate -> search -> save

# 4. Persistence: save a lead, restart the container, confirm it survives
#    (same -v ls_data:/var/data mount).

# 5. Isolation: run a SECOND container from the same image with a DIFFERENT
#    SECRETS_TOML_B64 and a different volume; confirm separate logins + data.
```
Confirm no secret values appear in `docker logs`.
