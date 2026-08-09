# READ-ONLY survey of product data quality. No writes, no commit.
# Run inside odoo shell:
#   odoo shell -d tecas19 -c /etc/odoo/odoo.conf --no-http < product_survey.py
# Covers: (A) attribute-value hygiene, (B) duplicate product.template candidates.
import re, csv, unicodedata, collections

OUT = "/tmp"
STUFFED_LEN = 30      # a spec value longer than this is almost certainly a description
STUFFED_WORDS = 4     # ...or one carrying this many words

T = env["product.template"].with_context(active_test=False)
P = env["product.product"].with_context(active_test=False)
A = env["product.attribute"].with_context(active_test=False)
V = env["product.attribute.value"].with_context(active_test=False)
PTAV = env["product.template.attribute.value"].with_context(active_test=False)


def norm(s):
    """Accent/case/punct-insensitive key for name comparison."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def count_by_product(model, field="product_id", ids=None):
    """{product_or_template_id: row_count} via read_group (cheap)."""
    if model not in env:
        return {}
    dom = [(field, "in", ids)] if ids else []
    try:
        groups = env[model].with_context(active_test=False).read_group(dom, ["id"], [field])
    except Exception:
        return {}
    out = {}
    for g in groups:
        val = g.get(field)
        if val:
            out[val[0] if isinstance(val, (list, tuple)) else val] = g[field + "_count"]
    return out


# ---------------------------------------------------------------- A. attributes
print("=" * 72)
print("A. ATTRIBUTE VALUE HYGIENE")
print("=" * 72)

values = V.search([])
used_value_ids = set(PTAV.search([]).mapped("product_attribute_value_id").ids)

attr_rows = []
val_rows = []
stuffed = []
unused = []
dup_within_attr = collections.defaultdict(list)   # (attr_id, normkey) -> [value ids]

for a in A.search([], order="name"):
    vals = values.filtered(lambda v: v.attribute_id.id == a.id)
    n_stuffed = n_unused = 0
    for v in vals:
        name = v.name or ""
        words = len(name.split())
        is_stuffed = len(name) > STUFFED_LEN or words >= STUFFED_WORDS
        is_unused = v.id not in used_value_ids
        n_stuffed += bool(is_stuffed)
        n_unused += bool(is_unused)
        dup_within_attr[(a.id, norm(name))].append(v.id)
        status = "STUFFED" if is_stuffed else "OK"
        if is_unused:
            status += "+UNUSED"
        val_rows.append((v.id, a.id, a.name, name, len(name), words,
                         "yes" if is_unused else "no", status))
        if is_stuffed:
            stuffed.append((a.name, v.id, name))
        if is_unused:
            unused.append((a.name, v.id, name))
    attr_rows.append((a.id, a.name, a.create_variant, len(vals), n_stuffed, n_unused))

dups_v = {k: ids for k, ids in dup_within_attr.items() if len(ids) > 1 and k[1]}

print(f"attributes: {len(attr_rows)}   values: {len(values)}   "
      f"used by a template: {len(used_value_ids & set(values.ids))}")
print(f"  STUFFED (len>{STUFFED_LEN} or >={STUFFED_WORDS} words): {len(stuffed)}")
print(f"  UNUSED  (no template references them):                 {len(unused)}")
print(f"  DUPLICATE values inside the same attribute:            {len(dups_v)}")
print("-" * 72)
print(f"{'attribute':32} {'vals':>5} {'stuffed':>8} {'unused':>7}  create_variant")
for aid, aname, cv, nv, ns, nu in sorted(attr_rows, key=lambda r: -r[4]):
    if nv:
        print(f"{(aname or '')[:32]:32} {nv:5d} {ns:8d} {nu:7d}  {cv}")

print("\n--- sample STUFFED values ---")
for aname, vid, name in sorted(stuffed, key=lambda r: -len(r[2]))[:12]:
    print(f"  [{(aname or '')[:18]:18}] id={vid:5d}  {name[:80]!r}")

print("\n--- duplicate values within one attribute ---")
for (aid, key), ids in sorted(dups_v.items(), key=lambda kv: -len(kv[1]))[:10]:
    names = [V.browse(i).name for i in ids]
    print(f"  attr={A.browse(aid).name!r:24} x{len(ids)}  {names[:3]}")

# ---------------------------------------------------------------- B. templates
print("\n" + "=" * 72)
print("B. DUPLICATE product.template CANDIDATES")
print("=" * 72)

tmpls = T.search([], order="id")
sale_cnt = count_by_product("sale.order.line", "product_id")
pur_cnt = count_by_product("purchase.order.line", "product_id")
move_cnt = count_by_product("stock.move", "product_id")

# variant-level counts rolled up to their template
var2tmpl = {p.id: p.product_tmpl_id.id for p in P.search([])}


def rollup(cnt):
    out = collections.Counter()
    for pid, n in cnt.items():
        t = var2tmpl.get(pid)
        if t:
            out[t] += n
    return out


sale_t, pur_t, move_t = rollup(sale_cnt), rollup(pur_cnt), rollup(move_cnt)

by_name = collections.defaultdict(list)
by_code = collections.defaultdict(list)
for t in tmpls:
    k = norm(t.name)
    if k:
        by_name[k].append(t.id)
    if t.default_code:
        by_code[norm(t.default_code)].append(t.id)

dup_name = {k: v for k, v in by_name.items() if len(v) > 1}
dup_code = {k: v for k, v in by_code.items() if len(v) > 1}
dup_ids = set(i for v in dup_name.values() for i in v)

pub_field = "is_published" if "is_published" in T._fields else None

print(f"templates: {len(tmpls)} (active {env['product.template'].search_count([])})   "
      f"variants: {P.search_count([])}")
print(f"  duplicate NAME groups:        {len(dup_name)}  covering {len(dup_ids)} templates")
print(f"  duplicate default_code groups:{len(dup_code)}")

tmpl_rows = []
for key, ids in sorted(dup_name.items(), key=lambda kv: -len(kv[1])):
    for tid in ids:
        t = T.browse(tid)
        tmpl_rows.append((
            key, tid, t.name, "yes" if t.active else "no",
            t.default_code or "", len(t.product_variant_ids),
            len(t.attribute_line_ids),
            sale_t.get(tid, 0), pur_t.get(tid, 0), move_t.get(tid, 0),
            "yes" if t.web_description else "no",
            "yes" if t.tech_sheet_pdf else "no",
            len(t.gallery_attachment_ids),
            "yes" if (pub_field and t[pub_field]) else "no",
            str(t.create_date)[:10],
        ))

print("\n--- top duplicate-name groups (docs = sale/purchase/stock rows) ---")
shown = 0
for key, ids in sorted(dup_name.items(), key=lambda kv: -len(kv[1])):
    if shown >= 12:
        break
    shown += 1
    print(f"  {key[:52]!r}  x{len(ids)}")
    for tid in ids:
        t = T.browse(tid)
        extras = []
        if t.web_description:
            extras.append("web_desc")
        if t.tech_sheet_pdf:
            extras.append("pdf")
        if t.gallery_attachment_ids:
            extras.append(f"gal{len(t.gallery_attachment_ids)}")
        print(f"      id={tid:5d} act={'Y' if t.active else 'n'} "
              f"var={len(t.product_variant_ids):3d} "
              f"docs={sale_t.get(tid,0):3d}/{pur_t.get(tid,0):3d}/{move_t.get(tid,0):3d} "
              f"code={(t.default_code or '-')[:14]:14} {' '.join(extras)}")

# ---------------------------------------------------------------- CSVs
with open(f"{OUT}/product_attr_values.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["value_id", "attribute_id", "attribute", "value", "len",
                "words", "unused", "status"])
    w.writerows(sorted(val_rows, key=lambda r: (-r[4], r[2])))

with open(f"{OUT}/product_attr_summary.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["attribute_id", "attribute", "create_variant", "values",
                "stuffed", "unused"])
    w.writerows(sorted(attr_rows, key=lambda r: -r[4]))

with open(f"{OUT}/product_tmpl_dupes.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name_key", "template_id", "name", "active", "default_code",
                "variants", "attr_lines", "sale_lines", "purchase_lines",
                "stock_moves", "web_description", "tech_sheet_pdf",
                "gallery_imgs", "published", "created"])
    w.writerows(tmpl_rows)

print("\nCSVs written to /tmp: product_attr_values.csv, product_attr_summary.csv, "
      "product_tmpl_dupes.csv")
print("=" * 72)
print("READ-ONLY — nothing was written to the database.")
