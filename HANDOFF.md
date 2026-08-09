# TECAS v19 — Data-Cleaning & Redesign Handoff

**Written:** 2026-08-09 · **For:** the next Claude Code session opened in `/opt/tecas-v19`
**Author of prior work:** a Claude Code session (context being discarded — this file is the memory).

---

## 0. Paste-this kickoff prompt

> You are continuing maintenance on TECAS, a **live production** Odoo 19 Enterprise instance
> (solar energy company, tecas.ma) in Docker inside an LXC container. Read `HANDOFF.md` and
> `maintenance/*.py` in this folder before doing anything. Two prior passes are DONE and
> committed to prod: (1) phone-number normalization, (2) a conservative partner-dedup merge of
> 25 groups. Audit logs + pre-change DB dumps are in `backups/`.
>
> **Operating rules (non-negotiable):**
> 1. This is prod (`tecas19` DB, container `tecas-db-19` / `tecas-web-19`). Take a fresh
>    `pg_dump` backup before ANY write. Never run `docker compose down -v` (destroys the DB volume).
> 2. Always dry-run read-only first, show me counts + samples, then apply in batches with per-row/
>    per-group commit and a CSV audit log written to `backups/`.
> 3. Never auto-merge partners with **different names** or **bare first-name-only** names
>    (e.g. "MR MOSTAPHA") or **conflicting phone/email**. "Do only what's safe."
> 4. Write partner changes through the **ORM** (recomputes `phone_sanitized`, which WhatsApp
>    matching depends on), never raw SQL on `res_partner.phone`.
>
> My next task is: **<pick from §6 Pending Work>**. Start by reading the relevant script and
> re-running its dry-run so I can see current numbers.

---

## 1. Environment map

**Two fully-isolated stacks on this host:**

| | Production | Staging |
|---|---|---|
| Compose file | `/opt/tecas-v19/docker-compose.yml` | `/opt/tecas-staging/docker-compose.yml` |
| Web container | `tecas-web-19` (host `:8069`, gevent `:8072`) | `tecas-web-staging` (host `:8169` / `:8172`) |
| DB container | `tecas-db-19` (pgvector/pg15) | `tecas-db-staging` (no host port) |
| DB name | `tecas19` | `tecas19_staging` |
| DB user/pass | `odoo19` / `odoo` | same |
| Volumes | `tecas-v19_tecas-db-data`, `tecas-v19_tecas-filestore` (**filestore is external**) | `tecas-staging_*` |
| Image | `tecas-web:v19` (built from `./Dockerfile`) | reuses the same image, read-only |

Custom addons (bind-mounted at `/mnt/user-addons`, prod copy under `./addons/`):
`tecas_extention`, `smfourniture_extention`, `tecas_product_webextras`, `whatsapp_x_ai_bot`.
Staging has its **own** copy of `./addons/` **plus** `tecas_website_theme` (the redesign addon,
not yet in prod).

**Run odoo shell (read-only work + scripts) like this:**
```bash
docker exec -i tecas-web-19 odoo shell -d tecas19 -c /etc/odoo/odoo.conf --no-http < SCRIPT.py 2>/dev/null
# scripts import helpers from /tmp, so copy them in first:
docker cp maintenance/phone_normalize.py tecas-web-19:/tmp/
```
Enterprise addons live at `/mnt/extra-addons` inside the container.
`phonenumbers` is pip-installed in the image (see `Dockerfile`).

---

## 2. Infra / restart fragility (unresolved — worth fixing)

- **`startup-fixes.sh` has no visible scheduler.** Its header says "runs on every boot via cron"
  but there is **no crontab/`/etc/cron.d` entry inside the container** for it or for `backup.sh`
  (backups DO run daily → the scheduler is on the **LXC/Proxmox host**, invisible/unmanaged from
  inside). **Consequence:** a plain `docker restart` / `compose up` does NOT re-apply the DB
  fixes, and the site can 500 on `/shop`, product pages, and invoice PDFs until `startup-fixes.sh`
  is run by hand. After any restart: run `startup-fixes.sh`, then check `/shop` + a product page +
  an invoice PDF.
- **`startup-fixes.sh` patches broken v16→v19 views at the DB level, not in code.** It deactivates/
  rewrites several `website_sale` views (`products_attributes_filters`, `alternative_products`,
  `badge_extra_price`, `variants`, `website_sale_stock_product`). If the DB is ever rebuilt from a
  clean dump, the breakage returns. The redesign must NOT depend on those views.
- **It also *generates* two source files** into `tecas_extention` if missing
  (`static/src/js/array_polyfill.js`, `static/src/css/statusbar_fix.css`) — both are referenced in
  the manifest `assets`. **These should be committed to git**, not generated at boot.
- **`backup.sh` backs up the prod DB only** — not the filestore (external volume, holds
  attachments/PDFs), not staging. 7-day retention.
- **`docker compose down -v` would destroy the prod DB** (`tecas-db-data` is NOT external, unlike
  the filestore). Only `down` without `-v` is safe.

---

## 3. Critical code facts the next agent MUST know

- **`res.partner` is `_inherit`-ed in THREE files** in `tecas_extention/models/`:
  - `res_partner.py` — `_check_phone_unique` + `_check_ice_unique` (exact-string, Python
    `ValidationError`); phone mandatory for persons, ICE (`x_studio_ice`) mandatory for companies;
    enforced on create & write.
  - `whatsapp_channel_sync.py` — `write()` override that syncs WhatsApp channel membership; **only
    acts when `'user_id' in vals`** and does `env.cr.commit()` + bus sends. Keep `user_id` OUT of
    bulk data writes so it stays dormant.
  - `sale_order.py` — adds `is_coa_installed` field to res.partner.
- **No `mobile` field** on res.partner in this v19 instance — only `phone`.
- **`phone_sanitized`** exists and drives WhatsApp/mail matching → always write phone via ORM.
- **The uniqueness constraints fire mid-merge** on same-phone/same-ICE pairs (source still exists
  during the merge) → they must be bypassed for merge/normalization jobs. Prior work did this by
  **monkeypatching `_check_phone_unique`/`_check_ice_unique` to no-ops in the odoo-shell session
  only** (auto-restored in `finally`) — prod code was NOT changed. See `maintenance/dedup_apply.py`.
- **Odoo Data Cleaning:** in v19 the `data_merge` models live in the **`data_cleaning`** module
  (`/mnt/extra-addons/data_cleaning/models/`). Merge entrypoint:
  `data_merge.group.merge_records(record_ids)`. For `res.partner` it calls the real
  `base.partner.merge.automatic.wizard.action_merge()` (moves all linked docs, deletes sources).
  Survivor is elected by `res.partner._elect_method` = **oldest active** record.
  The UI merge **times out** (`La connexion a expiré…`) on prod volumes — that's why we script it.

---

## 4. Work COMPLETED (committed to prod)

### 4a. Phone normalization — DONE
- **Convention:** Moroccan → `+212 XXX-XXXXXX` (3-6 grouping, uniform for mobile & landline);
  foreign → `phonenumbers` INTERNATIONAL (`+CC ...`).
- **Result:** 6,502 partners had a phone. **2,981 reformatted** (unique/singleton numbers only).
  Conforming rose 3,293 → 6,274. Written via ORM (phone_sanitized recomputed — verified).
- **Deliberately untouched:** duplicate-cluster numbers (see §6) and 88 flagged/garbage numbers.
- **Constraint:** never fired (only singletons touched) → no code change was needed for this pass.
- Scripts: `maintenance/phone_normalize.py` (shared), `phone_dryrun.py`, `phone_apply.py`.
- Audit: `backups/phone_applied.csv` (2,981 old→new), `phone_flagged.csv` (88), `phone_duplicates.csv`.
- Pre-change dump: `backups/tecas19_prephone_20260809_154438.dump`.

### 4b. Partner dedup — 25 safe merges DONE
- Used Odoo's own merge via script (no UI timeout), per-group commit, full log.
- **Safe filter** (all must hold): identical **title-stripped** name (≥2 tokens, so "MR MOSTAPHA"/
  "Mr Dalal" rejected), no conflicting phone (compared by digits, so fake `060606060` vs `050505050`
  counts as conflict), no conflicting email, same company_type, not linked to a res.users,
  similarity ≥ 90%.
- **25 of 771 groups merged, 0 errors.** Partner count 8,942 → 8,917. Sources deleted, survivors
  intact, documents moved (verified: survivor 7211 kept its 2 sale orders).
- Scripts: `maintenance/dedup_lib.py` (filter + classify), `dedup_dry.py`, `dedup_apply.py`.
- Audit: `backups/dedup_plan.csv` (**all 771 groups** + decision/reason), `dedup_results.csv` (25 merged).
- Pre-change dump: `backups/tecas19_premerge_20260809_161213.dump`.

---

## 5. Scripts inventory (`maintenance/`)

| File | Purpose | How to run |
|---|---|---|
| `phone_normalize.py` | shared `normalize(raw)` → `(canonical, kind)` | imported by the others |
| `phone_dryrun.py` | READ-ONLY classify all phones (OK/REFORMAT/FLAG/dupes) | via odoo shell |
| `phone_apply.py` | reformat unique phones via ORM, batched commit, writes CSVs | via odoo shell |
| `dedup_lib.py` | safe-merge `classify(env, group)` + name/phone normalizers, `SIM_MIN=0.90` | imported |
| `dedup_dry.py` | READ-ONLY classify all `data_merge` groups → `dedup_plan.csv` | via odoo shell |
| `dedup_apply.py` | merge SAFE groups via wizard, constraint-bypass, `dedup_results.csv` | via odoo shell |

Run pattern (copy helpers into the container's `/tmp` first — scripts `sys.path.insert(0,"/tmp")`):
```bash
for f in maintenance/*.py; do docker cp "$f" tecas-web-19:/tmp/; done
docker exec -i tecas-web-19 odoo shell -d tecas19 -c /etc/odoo/odoo.conf --no-http < maintenance/dedup_dry.py 2>/dev/null
```

---

## 6. PENDING work (prioritized)

### P1 — Remaining partner duplicates (~746 `data_merge` groups)
Breakdown from the last dry-run: 508 below 90% similarity, 127 different names, 108 single-token/
first-name-only, 2 conflicting phones. **Do NOT auto-merge** different-name or first-name-only
groups (client's explicit rule). Options: (a) build a **review sheet** grouping these for human
decision; (b) relax `SIM_MIN` / criteria in `dedup_lib.py` only for a subset the user has eyeballed.
Separately, the phone pass found **554 phone-value duplicate clusters / 1,380 partners**
(`phone_duplicates.csv`) — a different grouping than data_merge; reconcile when doing dedup.

### P2 — 88 flagged phone numbers (manual)
`backups/phone_flagged.csv`. Garbage/ambiguous: `"Mohammed install"`, `"0000000"`, two-numbers-in-
one-field (`"0522537340  0522537341"`), too-many-digits (`+2126616527228`). Needs human fixes; a
"split two-numbers-in-one-field into primary/secondary" helper would clear the easy ones.

### P3 — Product data cleaning (NOT started)
Second half of the data workstream: description-stuffed `product.attribute.value` and duplicate
`product.template`. **Start with a read-only survey** (like the phone survey) before any change.
Note custom fields to migrate when merging products (`tecas_product_webextras/models/product_template.py`):
`web_description` (Html), `tech_sheet_pdf`, `gallery_attachment_ids` (m2m `product_gallery_rel`).
Check `tecas_product_webextras/views/website_template.xml` + `hide_variant_price_extra.xml` don't
render attribute values in a way a cleanup would break.

### P4 — Website redesign (staging: `tecas_website_theme`)
- Top utility bar already built (`views/header_topbar.xml`, inherits `website.layout`, xpath before
  `//header#top`, class `bg-o-color-5`). **Navy header itself still TODO.**
- **Colors are hardcoded hex** across the SCSS (`#0A2540` navy, `#F5A623` amber, `#25D366` green) —
  not centralized; and the `ir.asset`/palette config lives **only in staging's DB**, not in code.
  Move it into code (SCSS vars + `ir_asset` data file) BEFORE promoting to prod.
- Promotion path: copy addon back to `/opt/tecas-v19/addons`, install `tecas_website_theme` in prod
  (not present there), `-u` it. No image rebuild (addons are bind-mounted).

### P5 — Infra hardening (see §2)
Commit the two boot-generated files to git; document/relocate the `startup-fixes.sh` scheduler;
extend `backup.sh` to cover the filestore.

---

## 7. Backups & audit files (`backups/`)
- `tecas19_YYYYMMDD.dump` — daily prod DB (7-day retention).
- `tecas19_prephone_20260809_154438.dump` — before phone normalization.
- `tecas19_premerge_20260809_161213.dump` — before the 25 merges.
- `phone_applied.csv`, `phone_flagged.csv`, `phone_duplicates.csv` — phone pass.
- `dedup_plan.csv` (all 771 groups), `dedup_results.csv` (25 merged) — dedup pass.
- **Restore a dump if needed:** `docker exec -i tecas-db-19 pg_restore -U odoo19 -d tecas19 --clean --if-exists < backups/<file>.dump` (stop web first; verify on staging before doing this to prod).
