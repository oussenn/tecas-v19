"""Put a homepage block underneath the one it belongs with.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/order_homepage_sections.py

TECAS_DRY=1 prints the plan and rolls back.

The blocks are stored html in the page, so their order is the order they sit in
website.accueil's arch — there is nothing to reorder in the module. This moves
whole <section> elements, touching nothing inside them, which matters for two
reasons: the client's own edits inside a block are carried across untouched,
and the fingerprint that models/tecas_autosync.py stamps on the self-updating
blocks stays valid, so they keep refreshing themselves afterwards.

Re-running is a no-op once the order is right.
"""

import os

from lxml import etree

DRY_RUN = os.environ.get('TECAS_DRY') == '1'

# {block to move: block it must sit directly underneath}
ORDER = {
    # The brands strip belonged to the hero, above the catalogue. The client
    # wants it read as "and here is what those categories are made of", which
    # only works below them.
    's_tecas_brands': 's_tecas_categories',
}

View = env['ir.ui.view'].sudo()
langs = env['res.lang'].sudo().with_context(active_test=True).search([]).mapped('code') or ['en_US']
# Source language first: writing arch_db in it regenerates the others, so any
# other order would have the later writes overwritten a moment after.
langs = sorted(set(langs), key=lambda code: code != 'en_US')

report = []


def section(root, class_name):
    found = root.xpath("//section[contains(@class, '%s')]" % class_name)
    return found[0] if found else None


for page in env['website.page'].sudo().search([]):
    for lang in langs:
        view = page.view_id.with_context(lang=lang)
        arch = view.arch_db or ''
        if not any(name in arch for name in ORDER):
            continue
        root = etree.fromstring(arch.encode('utf-8'))
        moved = False
        for mover_class, anchor_class in ORDER.items():
            mover = section(root, mover_class)
            anchor = section(root, anchor_class)
            if mover is None or anchor is None:
                continue
            if mover.getparent() is not anchor.getparent():
                report.append('%s: %s and %s are not siblings, skipped'
                              % (page.url, mover_class, anchor_class))
                continue
            if anchor.getnext() is mover:
                continue                                    # already in place
            # The tail is the whitespace that follows a node, so it belongs to
            # the position and not to the block; swapping them keeps the arch
            # laid out as it was.
            mover_tail, anchor_tail = mover.tail, anchor.tail
            anchor.addnext(mover)
            mover.tail, anchor.tail = anchor_tail, mover_tail
            moved = True
            report.append('%s (%s): %s moved below %s'
                          % (page.url, lang, mover_class, anchor_class))
        if moved and not DRY_RUN:
            view.write({'arch_db': etree.tostring(root, encoding='unicode')})

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for line in report or ['nothing to do — already in order']:
    print(' *', line)

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted — restart the web container so the compiled template follows')
