# Re-render the homepage's "Votre matériel solaire par type" tiles from the
# current published categories, and swap the result into the page.
#
#   docker exec -i tecas-web-19 odoo shell -d tecas19 \
#       -c /etc/odoo/odoo.conf --no-http < scripts/refresh_home_categories.py
#
# Run this after publishing products in a new category, or after renaming or
# reordering categories — the tiles on the page are a snapshot, not a live
# query, and this is what refreshes the snapshot.
#
# It is also the script that originally replaced the raw-QWeb section with its
# RENDERED output.
#
# Why: ir_ui_view.distribute_branding() pops a node's own editor branding when
# any descendant carries a t-* attribute (_contains_branded). The dynamic
# categories block put t-foreach/t-set/t-if inside #wrap, so #wrap lost its
# data-oe-model, stopped matching the builder's o_editable_selectors
# ("[data-oe-model]"), and the page ended up with zero drop zones — which is
# why every snippet category showed as undroppable.
#
# Dragging a snippet from the panel inserts RENDERED html, so a page never
# normally contains QWeb. This restores that invariant.

from lxml import etree

view = env['ir.ui.view'].browse(3645)
arch_en = view.with_context(lang='en_US').arch_db
arch_fr = view.with_context(lang='fr_FR').arch_db
print('en/fr archs identical:', arch_en == arch_fr)

root = etree.fromstring(arch_en.encode('utf-8'))
old = root.xpath("//section[contains(@class,'s_tecas_categories')]")
assert len(old) == 1, "expected exactly one categories section, got %d" % len(old)
old = old[0]

rendered = env['ir.qweb']._render('tecas_website_blocks.s_tecas_categories')
new = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8')).find('section')
assert new is not None, "render produced no <section>"

# Keep the editor identity attributes the drop originally added.
for attr in ('data-snippet', 'data-name'):
    if old.get(attr):
        new.set(attr, old.get(attr))
new.tail = old.tail

tiles = new.xpath(".//a[contains(@class,'s_tecas_cat_tile')]")
print('tiles rendered:', len(tiles))
print('hrefs:', [a.get('href') for a in tiles])
assert tiles, "refusing to freeze an empty categories block"

old.getparent().replace(old, new)
new_arch = etree.tostring(root, encoding='unicode')

leftover = [a for el in etree.fromstring(new_arch.encode('utf-8')).iter()
            if isinstance(el.tag, str)
            for a in el.attrib if a.startswith('t-')]
inner_t = etree.fromstring(new_arch.encode('utf-8')).xpath("//div[@id='wrap']//t")
print('t-* attrs left inside arch:', sorted(set(leftover)))
print('<t> elements left inside #wrap:', len(inner_t))
assert not inner_t, "still QWeb inside #wrap"

for lang in ('en_US', 'fr_FR'):
    view.with_context(lang=lang).write({'arch_db': new_arch})
env.cr.commit()

# Prove #wrap regains its branding.
check = etree.fromstring(env['ir.ui.view'].browse(3645).arch_db.encode('utf-8'))
env['ir.ui.view'].distribute_branding(
    check, {'data-oe-model': 'ir.ui.view', 'data-oe-id': '3645', 'data-oe-field': 'arch'})
w = check.xpath("//div[@id='wrap']")[0]
print('AFTER: #wrap data-oe-model =', repr(w.get('data-oe-model')))
