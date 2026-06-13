# Brief for Claude Code — Deployment & Cross-Client Update Workflow

## Objective

Make this tool deployable as one private codebase that can run as many isolated,
single-tenant client instances, all updatable from a single source of truth.
The operator hosts every instance on infrastructure they control; each client
receives only a URL and login credentials — never the repository, the container
image, or the source. This brief produces the deployment scaffolding (container,
ignore files, pinned dependencies), a provisioning runbook, and a safe rollout
process for pushing updates to all clients.

This assumes the storage-compliance fix is already merged. This is a
**decisions-pinned** brief: implement the decisions as written; do not
substitute alternatives. Ask before guessing where the code is genuinely
ambiguous.

## Background (the model this serves)

The business is custom software plus a maintenance retainer. IP protection comes
from the operator hosting the tool and gating it with the existing login — the
client never possesses the code. One private git repo is the single source of
truth; the code is byte-identical across all clients, and only per-client secrets
differ. Improving the product for everyone means changing the core once and
rolling it out to each instance.

## Pinned decisions

**D1 — Deployment unit is a Docker image.**
Containerize the app so every instance is reproducible and identical. The hard
requirements (host-agnostic):
- The operator controls the hosting account/infrastructure; the client gets only
  a URL + login.
- A **persistent disk/volume** holds the SQLite database (default container
  storage is ephemeral and wipes on restart — this is non-negotiable).
- Secrets are injected at **runtime**, never baked into the image or committed.
- HTTPS in front of the app.
Recommended default host: a PaaS with persistent-disk support (e.g., Render or
Railway) for simplicity; a small VPS running the container is the option once
instance count makes per-instance PaaS cost the larger factor. Pick the host that
meets the four requirements above; the rest of this brief is host-agnostic.

**D2 — One private repo, identical code, secrets are the only per-client diff.**
Nothing client-specific is committed. Onboarding a client = deploy this image +
supply that client's secrets. Confirm `.gitignore` excludes `secrets.toml`,
`*.db`, `.env`, `__pycache__/`, and the venv.

**D3 — Secrets delivery into the container.**
`config.py` reads top-level keys from env but reads the nested `[auth.users.*]`
table from a Streamlit secrets file. To keep `config.py`/`auth.py` unchanged and
work on any host, the container entrypoint materializes
`.streamlit/secrets.toml` at startup from a single base64-encoded env var
`SECRETS_TOML_B64`, writes it with `600` permissions, and then execs Streamlit.
The entrypoint must never echo or log the secret contents. (If the chosen host
has a native "secret file" feature, that may be used instead — but ship the
entrypoint approach so the image is portable.)

**D4 — Database path is configurable.**
Change `database.py` so `DB_PATH` reads from env var `LEADS_DB_PATH`, defaulting
to `leads.db` for local use. In deployment this points to a file on the mounted
persistent volume. This is the only application-code change in this brief.

**D5 — Rollout is staged, never push-to-all.**
Do NOT wire auto-deploy-on-push that updates every client at once — one bad
commit must not break every client simultaneously. Instead:
- Tag releases (e.g., `v1.3.0`).
- Deploy the tag to a **staging/canary instance** the operator owns (configured
  like a real client) and verify it there first.
- Promote the verified tag to each client instance **one at a time**.
- Keep the previous tag deployable for fast rollback.
Provide a documented, scriptable rollout sequence (a shell script or Makefile
targets) that takes a tag and an instance identifier and performs deploy +
health check, plus a rollback target that redeploys the prior tag.

**D6 — Per-instance backups.**
Provide a scheduled backup of each instance's `leads.db` from the persistent
volume (a cron/scheduled-job script that copies the DB to timestamped backup
storage). Each client's saved leads/status/notes are the client's data; this
protects it independently of the code.

**D7 — Offboarding = disable, not delete.**
Document the offboarding step: disable the instance and revoke the client's
login (the kill switch). Do not hard-delete the client's data as part of
offboarding; retention/disposal is a contract matter handled separately.

## Deliverables (files to create)

- `Dockerfile` — base on `python:3.12-slim`; install pinned `requirements.txt`;
  run as a non-root user; copy app code (excluding anything in
  `.dockerignore`); set an entrypoint script (D3); run
  `streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0
  --server.headless=true --browser.gatherUsageStats=false`; add a healthcheck
  hitting Streamlit's `/_stcore/health` endpoint.
- `entrypoint.sh` — implements D3 (decode `SECRETS_TOML_B64` →
  `.streamlit/secrets.toml`, chmod 600, never log), then `exec` Streamlit.
- `.dockerignore` — exclude `.git`, secrets, `*.db`, venvs, `__pycache__`,
  backups.
- `.gitignore` — per D2 (if not already present/correct).
- `requirements.txt` — pinned, including `streamlit`, `streamlit-authenticator>=0.4,<0.5`,
  `bcrypt>=4`, plus the existing deps (`anthropic`, `requests`, `python-dotenv`,
  `openpyxl`, `pydantic`, `pandas`). Pin to known-good versions.
- `deploy/rollout.sh` (or `Makefile`) — implements D5: `deploy <tag> <instance>`
  and `rollback <instance>` with a post-deploy health check.
- `deploy/backup.sh` — implements D6.
- `RUNBOOK.md` — the operator's onboarding checklist (see below) and the
  rollout/rollback/backup procedures.

## RUNBOOK.md must include this onboarding checklist

A repeatable "new client in N minutes" sequence:
1. Create a new instance/service on the host; attach a persistent volume; set
   `LEADS_DB_PATH` to a path on that volume.
2. Generate the client's secrets: their `GOOGLE_PLACES_API_KEY` and
   `ANTHROPIC_API_KEY` (client brings their own), a unique `COOKIE_NAME` and a
   freshly random `COOKIE_KEY`, `CLIENT_NAME`, and one `[auth.users.*]` block per
   user with a bcrypt hash from `gen_password_hash.py`.
3. Base64-encode the finished `secrets.toml` and set it as `SECRETS_TOML_B64` in
   the instance's secret store.
4. Deploy the current released tag to the instance.
5. Smoke test: confirm HTTPS load, login gate blocks an unauthenticated session,
   a valid login works, a search returns results, save + My Leads display work.
6. Hand the client only the URL and their credentials.

## Acceptance criteria — RUN IT, don't just compile it

Demonstrate each by actually doing it:
1. `docker build` succeeds; image runs locally.
2. With NO secrets baked into the image, the container starts when
   `SECRETS_TOML_B64` is provided at runtime, and fails clearly (not silently)
   when it is absent. Confirm no secret values appear in container logs.
3. The login gate works in the container; a search and save work end-to-end.
4. **Persistence:** save a lead, restart the container, and confirm the lead
   survives (DB is on the mounted volume, not image/ephemeral storage).
5. **Isolation:** stand up a SECOND instance from the SAME image with different
   secrets; confirm the two have separate logins and separate data, and that
   neither can see the other's leads.
6. **Rollout:** `deploy <tag> <staging>` deploys and passes its health check;
   promoting the same tag to a second instance works; `rollback` restores the
   prior tag.
7. **Backup:** `deploy/backup.sh` produces a timestamped copy of an instance's
   `leads.db`.
8. Confirm the client-facing surface is URL + login only — no repo, image, or
   source is required on or accessible from the client side.

## Out of scope / do not touch
- Application/UI logic, the Search→Save→Export flow, the qualification system
  prompt and scoring/flag logic (the protected IP).
- The `auth.py` / `config.py` access-control layer (other than the `DB_PATH` env
  change in `database.py`).
- Multi-tenant features — the model is one isolated instance per client.
- Any change that bakes secrets into the image or commits them to the repo.
