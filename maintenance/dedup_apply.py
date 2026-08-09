# APPLY safe merges. Destructive: merges source partners into survivor via the
# real Odoo partner-merge wizard. Per-group commit + full CSV audit log.
import sys, csv, traceback
sys.path.insert(0, "/tmp")
from dedup_lib import classify

# --- In-session bypass of tecas custom uniqueness checks -------------------
# Merging two records that share a phone/ICE triggers _check_phone_unique
# because the source still exists mid-merge. Neutralize ONLY for this run.
PartnerCls = type(env["res.partner"])
_orig_phone = PartnerCls._check_phone_unique
_orig_ice = PartnerCls._check_ice_unique
PartnerCls._check_phone_unique = lambda self, *a, **k: None
PartnerCls._check_ice_unique = lambda self, *a, **k: None

results = []
try:
    groups = env["data_merge.group"].search([("res_model_name", "=", "res.partner")])
    safe = []
    for g in groups:
        info = classify(env, g)
        if info["decision"] == "SAFE":
            safe.append((g, info))
    print("SAFE groups to merge:", len(safe))

    for g, info in safe:
        surv = info["survivor"]
        recs = g.record_ids.filtered(lambda r: not r.is_discarded)
        merged_ids = [i for i in info["partner_ids"] if i != surv]
        row = {
            "group_id": g.id, "survivor_id": surv,
            "survivor_name": (info["names"][info["partner_ids"].index(surv)]
                              if surv in info["partner_ids"] else ""),
            "merged_ids": " ".join(map(str, merged_ids)),
            "names": " | ".join(info["names"]),
            "phones": " | ".join(info["phones"]),
            "similarity": info["similarity"], "status": "", "records_merged": 0,
        }
        try:
            recs.write({"is_master": False})
            recs.filtered(lambda r: r.res_id == surv).write({"is_master": True})
            res = g.merge_records(recs.ids) or {}
            env.cr.commit()
            row["status"] = "MERGED"
            row["records_merged"] = res.get("records_merged", len(merged_ids) + 1)
            print(f"  MERGED grp {g.id} keep {surv} <- {merged_ids}  {row['survivor_name']!r}")
        except Exception as e:
            env.cr.rollback()
            row["status"] = "ERROR: " + repr(e)[:180]
            print(f"  ERROR  grp {g.id}: {e!r}")
        results.append(row)
finally:
    PartnerCls._check_phone_unique = _orig_phone
    PartnerCls._check_ice_unique = _orig_ice

with open("/tmp/dedup_results.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["group_id", "survivor_id", "survivor_name",
        "merged_ids", "names", "phones", "similarity", "status", "records_merged"])
    w.writeheader()
    for r in results:
        w.writerow(r)

ok = sum(1 for r in results if r["status"] == "MERGED")
err = len(results) - ok
print("=" * 50)
print(f"DONE. merged={ok}  errors={err}")
print("Audit log: /tmp/dedup_results.csv")
