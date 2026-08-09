# READ-ONLY cleanup plan for product attribute data. No writes, no commit.
# Run inside odoo shell:
#   odoo shell -d tecas19 -c /etc/odoo/odoo.conf --no-http < product_cleanup_dry.py
#
# Produces three proposals, each classified so nothing ambiguous is ever auto-applied:
#   T1  delete unused attribute values + empty attributes   (no template references them)
#   T2  merge case/spacing-duplicate values inside one attribute
#   T3  replace description-stuffed values with an extracted spec token
import sys, csv, collections
sys.path.insert(0, "/tmp")
from product_lib import norm, is_stuffed, classify, STUFFED_LEN, STUFFED_WORDS

OUT = "/tmp"

A = env["product.attribute"].with_context(active_test=False)
V = env["product.attribute.value"].with_context(active_test=False)
PTAV = env["product.template.attribute.value"].with_context(active_test=False)
T = env["product.template"].with_context(active_test=False)


# value_id -> [template ids] that actually use it
val_templates = collections.defaultdict(set)
for ptav in PTAV.search([]):
    val_templates[ptav.product_attribute_value_id.id].add(ptav.product_tmpl_id.id)

values = V.search([])
attrs = A.search([])

# ------------------------------------------------------------------ T1: unused
t1_vals, t1_attrs = [], []
for v in values:
    if not val_templates.get(v.id):
        t1_vals.append((v.id, v.attribute_id.id, v.attribute_id.name, v.name or ""))
for a in attrs:
    if not a.value_ids:
        t1_attrs.append((a.id, a.name or "", 0))
    elif all(not val_templates.get(v.id) for v in a.value_ids):
        # every value is unused -> the whole attribute is dead weight
        t1_attrs.append((a.id, a.name or "", len(a.value_ids)))

print("=" * 74)
print("T1  UNUSED — referenced by no product template")
print("=" * 74)
print(f"  attribute VALUES with 0 template references: {len(t1_vals)} of {len(values)}")
print(f"  ATTRIBUTES entirely unused (all values dead): {len(t1_attrs)} of {len(attrs)}")
print("\n  --- attributes proposed for removal ---")
for aid, name, nv in sorted(t1_attrs, key=lambda r: r[1].lower()):
    print(f"    id={aid:4d} values={nv:3d}  {name[:56]!r}")
print("\n  --- sample unused values ---")
for vid, aid, aname, vname in t1_vals[:10]:
    print(f"    id={vid:5d} [{aname[:18]:18}] {vname[:52]!r}")

# ------------------------------------------------- T2: case/spacing duplicates
buckets = collections.defaultdict(list)
for v in values:
    buckets[(v.attribute_id.id, norm(v.name))].append(v)

t2 = []
for (aid, key), vs in buckets.items():
    if len(vs) < 2 or not key:
        continue
    used = [v for v in vs if val_templates.get(v.id)]
    tmpl_sets = [val_templates.get(v.id, set()) for v in vs]
    overlap = set.intersection(*tmpl_sets) if all(tmpl_sets) else set()
    if len(used) <= 1:
        # only one side is real -> the others are simply deletable
        decision, reason = "SAFE_DELETE_DUPE", "only_one_side_used"
    elif overlap:
        # same template carries both spellings -> merging would collide
        decision, reason = "REVIEW", "both_used_on_same_template"
    else:
        decision, reason = "MERGE", "both_used_different_templates"
    # keeper = the used one, else the lowest id; prefer the tidier spelling
    keeper = (used or vs)[0]
    for v in (used or vs):
        if (v.name or "").isupper() and not (keeper.name or "").isupper():
            continue
        keeper = v
        break
    t2.append({
        "attribute": A.browse(aid).name,
        "decision": decision, "reason": reason,
        "keep_id": keeper.id, "keep_name": keeper.name,
        "drop": [(v.id, v.name, len(val_templates.get(v.id, ()))) for v in vs if v.id != keeper.id],
    })

print("\n" + "=" * 74)
print("T2  DUPLICATE VALUES inside one attribute (case/spacing)")
print("=" * 74)
c2 = collections.Counter(r["decision"] for r in t2)
print(f"  groups: {len(t2)}   " + "  ".join(f"{k}={v}" for k, v in c2.items()))
for r in t2:
    drops = ", ".join(f"{n!r}(id={i},used_by={u})" for i, n, u in r["drop"])
    print(f"    [{r['decision']:16}] {r['attribute'][:16]:16} keep {r['keep_name']!r:34} drop {drops}")

# ------------------------------------------------------- T3: stuffed -> token
t3 = []
for v in values:
    name = v.name or ""
    if not is_stuffed(name):
        continue
    tmpls = val_templates.get(v.id, set())
    prop, conf, why = classify(v.attribute_id.name, name)
    t3.append((v.id, v.attribute_id.name, name, prop, conf, why, len(tmpls),
               " ".join(str(i) for i in sorted(tmpls))))

print("\n" + "=" * 74)
print("T3  DESCRIPTION-STUFFED VALUES -> extracted spec token")
print("=" * 74)
c3 = collections.Counter(r[4] for r in t3)
print(f"  stuffed values: {len(t3)}   AUTO={c3.get('AUTO',0)}  REVIEW={c3.get('REVIEW',0)}")
print(f"  (AUTO = exactly one unambiguous token extracted; everything else needs a human)")
print("\n  --- sample AUTO proposals ---")
for r in [x for x in t3 if x[4] == "AUTO"][:14]:
    print(f"    [{r[1][:16]:16}] {r[2][:46]!r:48} -> {r[3]!r:12} (used by {r[6]} tmpl)")
print("\n  --- sample REVIEW ---")
for r in [x for x in t3 if x[4] == "REVIEW"][:10]:
    print(f"    [{r[1][:16]:16}] {r[2][:46]!r:48} -> {r[3]!r:12} {r[5]}")

# ------------------------------------------------------------------------ CSVs
with open(f"{OUT}/product_t1_unused.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["kind", "id", "attribute_id", "attribute", "name", "values"])
    for vid, aid, aname, vname in t1_vals:
        w.writerow(["value", vid, aid, aname, vname, ""])
    for aid, name, nv in t1_attrs:
        w.writerow(["attribute", aid, aid, name, name, nv])

with open(f"{OUT}/product_t2_dupe_values.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["decision", "reason", "attribute", "keep_id", "keep_name",
                "drop_id", "drop_name", "drop_used_by_templates"])
    for r in t2:
        for i, n, u in r["drop"]:
            w.writerow([r["decision"], r["reason"], r["attribute"],
                        r["keep_id"], r["keep_name"], i, n, u])

with open(f"{OUT}/product_t3_stuffed.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["value_id", "attribute", "current_value", "proposed_value",
                "confidence", "reason", "template_count", "template_ids"])
    w.writerows(sorted(t3, key=lambda r: (r[4], r[1])))

print("\nCSVs written to /tmp: product_t1_unused.csv, product_t2_dupe_values.csv, "
      "product_t3_stuffed.csv")
print("=" * 74)
print("READ-ONLY — nothing was written to the database.")
