"""Turn the header's green WhatsApp button into a blue "Contactez-Nous", and
take the now-duplicate "Contactez-Nous" entry out of the menu.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/header_contact_button.py

TECAS_DRY=1  print what would change and roll back.

Why a script and not a module view: the header call to action was built in the
website editor, so it lives in the database as a hand-edited copy of
website.placeholder_header_call_to_action. A module view cannot reach inside
it, and re-creating it from the module would take the block away from the
client, who must still be able to restyle it from the editor afterwards.

WhatsApp itself is not lost — it moves to the round green button that
views/whatsapp_float.xml pins to the bottom-left corner, next to the chat
bubble, which is where a visitor now looks for it.
"""

import os

from lxml import etree

DRY_RUN = os.environ.get('TECAS_DRY') == '1'

CTA_PARENT = 'website.placeholder_header_call_to_action'
# The class the editor left on the button; it is what identifies it inside an
# arch that is otherwise a wall of tooltip ids and inline styles.
CTA_MARK = 'btn_ca'
# The page the menu entry pointed at, so the button lands where the menu did.
CONTACT_URL = '/demande-devis'
CONTACT_LABEL = 'Contactez-Nous'
# The logo's blue, i.e. --tecas-blue in static/src/scss/blocks.scss. Written
# inline rather than as a class: the arch belongs to the client's editor, and
# an inline colour is what the editor's own colour picker reads and rewrites.
BLUE = '#1D3C9B'

View = env['ir.ui.view'].sudo()
Menu = env['website.menu'].sudo()
Lang = env['res.lang'].sudo().with_context(active_test=True)

langs = Lang.search([]).mapped('code') or ['en_US']
report = []


def new_button():
    """The replacement anchor: same hooks, blue, pointing at the contact page.

    _cta and btn_ca are the theme's and the editor's own handles on this
    button; oe_unremovable is what stops someone deleting the header's only
    call to action by accident. All three are kept.
    """
    a = etree.Element('a')
    a.set('href', CONTACT_URL)
    a.set('class', '_cta btn btn-custom btn-sm oe_unremovable btn_ca tecas_header_cta')
    a.set('style', 'background-color: %s; border: 1px solid %s; color: #fff;' % (BLUE, BLUE))
    strong = etree.SubElement(a, 'strong')
    strong.text = CONTACT_LABEL
    return a


parent = env.ref(CTA_PARENT, raise_if_not_found=False)
views = View.search([('inherit_id', '=', parent.id)]) if parent else View.browse()
views = views.filtered(lambda v: CTA_MARK in (v.arch_db or ''))

for view in views:
    for lang in langs:
        record = view.with_context(lang=lang)
        arch = record.arch_db or ''
        if CTA_MARK not in arch:
            continue
        root = etree.fromstring(arch.encode('utf-8'))
        buttons = root.xpath("//a[contains(@class,'%s')]" % CTA_MARK)
        if not buttons:
            continue
        for old in buttons:
            new = new_button()
            new.tail = old.tail
            old.getparent().replace(old, new)
        updated = etree.tostring(root, encoding='unicode')
        if updated != arch:
            report.append('view %s (%s): call to action rewritten' % (view.id, lang))
            if not DRY_RUN:
                record.write({'arch_db': updated})

if not views:
    report.append('no header call to action found — nothing to rewrite')

# The menu entry and the button would now say the same thing, side by side.
menus = Menu.search([('url', '=', CONTACT_URL), ('child_id', '=', False)])
for menu in menus:
    report.append('menu %s "%s" (%s) removed from the nav bar'
                  % (menu.id, menu.name, menu.url))
if menus and not DRY_RUN:
    menus.unlink()

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for line in report:
    print(' *', line)

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted')
