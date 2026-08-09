# DRY RUN: classify all res.partner data_merge groups. READ-ONLY.
import sys, csv, collections
sys.path.insert(0, "/tmp")
from dedup_lib import classify

groups = env["data_merge.group"].search([("res_model_name", "=", "res.partner")])
print("res.partner duplicate groups:", len(groups))

rows, reasons = [], collections.Counter()
for g in groups:
    r = classify(env, g)
    reasons[(r["decision"], r["reason"])] += 1
    rows.append(r)

safe = [r for r in rows if r["decision"] == "SAFE"]
print("=" * 60)
print("SAFE to merge:", len(safe), "groups")
print("SKIP:", sum(1 for r in rows if r["decision"] == "SKIP"), "groups")
print("-" * 60)
for (dec, reason), n in reasons.most_common():
    print(f"  {dec:5} {reason:28} {n}")
print("=" * 60)

with open("/tmp/dedup_plan.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["group_id", "decision", "reason", "similarity", "survivor_id",
                "partner_ids", "names", "phones"])
    for r in rows:
        w.writerow([r["group_id"], r["decision"], r["reason"], r["similarity"],
                    r["survivor"], " ".join(map(str, r["partner_ids"])),
                    " | ".join(r["names"]), " | ".join(r["phones"])])
print("Plan written: /tmp/dedup_plan.csv")

print("\n--- sample SAFE merges ---")
for r in safe[:12]:
    print(f"  grp {r['group_id']:6} sim={r['similarity']:.2f} keep {r['survivor']:6} "
          f"<- {r['partner_ids']}  {r['names'][0]!r}")
