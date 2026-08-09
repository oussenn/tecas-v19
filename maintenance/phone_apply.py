# APPLY: reformat ONLY singleton (non-duplicate) parseable phones via ORM.
# - Duplicate-cluster partners: left untouched (reported to CSV).
# - Flagged (invalid/unparseable): left untouched (reported to CSV).
# Writes 'phone' only -> phone_sanitized recomputes; whatsapp write() hook stays dormant
# (it only acts on 'user_id'); _check_phone_unique never fires (singletons only).
import sys, csv, collections
sys.path.insert(0, "/tmp")
from phone_normalize import normalize

Partner = env["res.partner"].with_context(active_test=False)
partners = Partner.search([("phone", "!=", False), ("phone", "!=", "")])

norm_map = collections.defaultdict(list)
info = {}   # id -> (current, norm, kind)
for p in partners:
    norm, kind = normalize(p.phone)
    final = norm if norm else p.phone
    norm_map[final].append(p.id)
    info[p.id] = (p.phone, norm, kind)

dup_ids = set(i for v, ids in norm_map.items() if len(ids) > 1 for i in ids)

to_write = []   # (id, current, norm)
flagged  = []
skipped_dup = 0
for pid, (cur, norm, kind) in info.items():
    if norm is None:
        flagged.append((pid, cur, kind)); continue
    if pid in dup_ids:
        skipped_dup += 1; continue
    if norm != cur:
        to_write.append((pid, cur, norm))

print(f"Partners with phone: {len(partners)}")
print(f"  will REFORMAT (unique only): {len(to_write)}")
print(f"  skipped (duplicate cluster): {skipped_dup}")
print(f"  flagged (manual fix):        {len(flagged)}")

# Export reports (dup + flagged) for follow-up
with open("/tmp/phone_flagged.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "current_phone", "kind"])
    for pid, cur, kind in sorted(flagged):
        w.writerow((pid, cur, kind))
with open("/tmp/phone_duplicates.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["normalized_value", "count", "partner_ids"])
    for v, ids in sorted(((v, ids) for v, ids in norm_map.items() if len(ids) > 1),
                         key=lambda kv: -len(kv[1])):
        w.writerow((v, len(ids), " ".join(map(str, ids))))
with open("/tmp/phone_applied.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "old_phone", "new_phone"])
    for pid, cur, norm in to_write:
        w.writerow((pid, cur, norm))

# APPLY in batches with commit
BATCH = 200
done = 0
for i in range(0, len(to_write), BATCH):
    for pid, cur, norm in to_write[i:i+BATCH]:
        Partner.browse(pid).write({"phone": norm})
    env.cr.commit()
    done += len(to_write[i:i+BATCH])
    print(f"  committed {done}/{len(to_write)}")

print("APPLY COMPLETE. Reports: /tmp/phone_applied.csv, phone_flagged.csv, phone_duplicates.csv")
