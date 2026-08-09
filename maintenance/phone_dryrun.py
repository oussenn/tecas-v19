# Dry-run: classify all res.partner phones. READ-ONLY (no writes/commit).
# Run inside odoo shell:  odoo shell -d <db> -c /etc/odoo/odoo.conf < phone_dryrun.py
import sys, csv, collections
sys.path.insert(0, "/tmp")
from phone_normalize import normalize

Partner = env["res.partner"].with_context(active_test=False)
partners = Partner.search([("phone", "!=", False), ("phone", "!=", "")])

rows = []          # (id, name, current, normalized, kind)
counts = collections.Counter()
norm_map = collections.defaultdict(list)   # final_value -> [ids]

for p in partners:
    norm, kind = normalize(p.phone)
    counts[kind] += 1
    final = norm if norm else p.phone
    norm_map[final].append(p.id)
    changed = bool(norm) and norm != p.phone
    if not norm:
        status = "FLAG"
    elif changed:
        status = "REFORMAT"
    else:
        status = "OK"
    counts[status] += 1
    rows.append((p.id, (p.name or "")[:40], p.phone, norm or "", kind, status))

# Collisions: a normalized value shared by >1 partner
dup_groups = {v: ids for v, ids in norm_map.items() if len(ids) > 1}
dup_partner_ids = set(i for ids in dup_groups.values() for i in ids)

print("=" * 60)
print("TOTAL with phone:        ", len(partners))
print("  OK (already target):   ", counts["OK"])
print("  REFORMAT (safe change):", counts["REFORMAT"])
print("  FLAG (invalid/unparse):", counts["FLAG"])
print("-" * 60)
print("  kind: MA=%d  INTL=%d  invalid=%d  unparseable=%d  empty=%d"
      % (counts["ma"], counts["intl"], counts["invalid"], counts["unparseable"], counts["empty"]))
print("-" * 60)
print("DUPLICATE clusters:      ", len(dup_groups),
      "  covering partners:", len(dup_partner_ids))
print("=" * 60)

# Write full reports to /tmp for inspection
with open("/tmp/phone_changes.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "name", "current_phone", "normalized", "kind", "status"])
    for r in sorted(rows, key=lambda x: x[5]):
        w.writerow(r)

with open("/tmp/phone_flagged.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "name", "current_phone", "kind"])
    for r in rows:
        if r[5] == "FLAG":
            w.writerow((r[0], r[1], r[2], r[4]))

with open("/tmp/phone_duplicates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["normalized_value", "partner_count", "partner_ids"])
    for v, ids in sorted(dup_groups.items(), key=lambda kv: -len(kv[1])):
        w.writerow((v, len(ids), " ".join(map(str, ids))))

print("Reports written: /tmp/phone_changes.csv, phone_flagged.csv, phone_duplicates.csv")

# Show a few flagged + top duplicates inline
print("\n--- sample FLAGGED (need manual fix) ---")
for r in [x for x in rows if x[5] == "FLAG"][:12]:
    print(f"  id={r[0]:6}  {r[2]!r:22}  {r[4]}")
print("\n--- top DUPLICATE clusters ---")
for v, ids in sorted(dup_groups.items(), key=lambda kv: -len(kv[1]))[:10]:
    print(f"  {v:20}  x{len(ids)}")
