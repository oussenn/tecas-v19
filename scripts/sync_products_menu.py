# Turn "Nos Produits" into a dropdown listing the shop categories that
# actually have published products.
#
# Categories with nothing published 404 on /shop/category/<id>, so the same
# filter used by the homepage tiles is applied here — a menu entry is only
# created for a category a visitor can actually open.
#
# Idempotent: re-running syncs the children to the current category set.

PARENT_ID = 7          # "Nos Produits", website 1
SHOP_LABEL = 'Toute la boutique'

Menu = env['website.menu']
Cat = env['product.public.category']
slug = env['ir.http']._slug

parent = Menu.browse(PARENT_ID)
assert parent.exists(), 'parent menu missing'
print('parent: %s (url=%s, website=%s)' % (parent.name, parent.url, parent.website_id.id))

cats = Cat.sudo().search([('parent_id', '=', False)], order='sequence, name')
wanted = []
for c in cats:
    if env['product.template'].sudo().search_count(
            [('public_categ_ids', 'child_of', c.id), ('is_published', '=', True)]):
        wanted.append((c.name.strip(), '/shop/category/%s' % slug(c)))
wanted.append((SHOP_LABEL, '/shop'))

existing = Menu.search([('parent_id', '=', PARENT_ID)])
print('existing children: %d' % len(existing))
by_url = {m.url: m for m in existing}

seq = 10
kept, created = [], []
for name, url in wanted:
    m = by_url.pop(url, None)
    if m:
        m.write({'name': name, 'sequence': seq})
        kept.append(url)
    else:
        Menu.create({'name': name, 'url': url, 'parent_id': PARENT_ID,
                     'sequence': seq, 'website_id': parent.website_id.id or 1})
        created.append(url)
    seq += 10

stale = list(by_url.values())
for m in stale:
    print('  removing stale child:', m.name, m.url)
    m.unlink()

env.cr.commit()

print('created: %d, updated: %d, removed: %d' % (len(created), len(kept), len(stale)))
print('--- resulting dropdown ---')
for m in Menu.search([('parent_id', '=', PARENT_ID)], order='sequence'):
    print('   %-4s %-38s %s' % (m.sequence, m.name, m.url))
