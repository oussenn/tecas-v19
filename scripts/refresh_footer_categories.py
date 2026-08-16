"""Rebuild the "Nos produits" column of the footer from the live categories.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/refresh_footer_categories.py

The footer block is dynamic in its template but frozen in the site: dropping a
snippet copies its rendered html, so the live footer still listed the category
names of the day it was dropped — "ONDULEUR SOLAIRE OFF-GRID HYBRIDE",
"BATTERIES", and a link to PROMO that now answers 404 because the category was
hidden from the website. This rewrites that one list, in place.

Only the <ul class="s_tecas_footer_cats"> is touched, and only in views that
hold a COPY of the block. The module's own template
(tecas_website_blocks.s_tecas_footer) is skipped on purpose: rewriting it would
replace its t-foreach with frozen html and break every future drop — the exact
trap that already cost this project a page once.
"""

from lxml import etree

from odoo.addons.tecas_website_blocks.models.tecas_autosync import AUTO_FLAG  # noqa: F401

LIST_CLASS = 's_tecas_footer_cats'
OWN_TEMPLATE_PREFIX = 'tecas_website_blocks.'
LIMIT = 6

Category = env['product.public.category'].sudo()
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')       # source first

views = env['ir.ui.view'].sudo().search([('arch_db', 'like', LIST_CLASS)])
views = views.filtered(lambda v: not (v.key or '').startswith(OWN_TEMPLATE_PREFIX))
if not views:
    raise SystemExit('no footer copy found — nothing to refresh')

categories = Category._tecas_homepage_tiles(LIMIT)
print('categories:', [(c.id, c.name) for c in categories])

for view in views:
    for lang in langs:
        view_lang = view.with_context(lang=lang)
        root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
        lists = root.xpath("//ul[contains(@class,'%s')]" % LIST_CLASS)
        if not lists:
            continue
        changed = False
        for node in lists:
            wanted = etree.fromstring(
                ('<ul>%s<li><a href="/shop">Tous les produits</a></li></ul>' % ''.join(
                    '<li><a href="/shop/category/%s">%s</a></li>' % (c.id, c.name)
                    for c in categories)).encode('utf-8'))
            def items(ul):
                return b''.join(etree.tostring(li) for li in ul)

            if items(node) == items(wanted):
                continue
            for child in list(node):
                node.remove(child)
            for child in list(wanted):
                node.append(child)
            changed = True
        if changed:
            view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
            print('%s / %s (%s): rebuilt' % (view.id, view.key, lang))

env.cr.commit()
print('committed — restart the web container so the compiled template follows')
