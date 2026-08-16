"""Homepage: drop the "Nos solutions" block, add "Nos Actualités" before the footer.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/swap_solutions_for_news.py

The news block goes last inside #wrap, which is the last thing above the site
footer (the footer lives in the layout, not in the page).

Two rules this file exists to respect, both learned the hard way:

  * A page is only changed by rewriting its arch — editing a snippet template
    does nothing to a page that already holds a copy of it.
  * Writing arch_db in the SOURCE language regenerates every other language
    from it, so each language is re-read inside the loop and skipped if the
    block is already there. Without that the block lands twice.

The removed "Nos solutions" block stays available in the editor; only this
page loses it.
"""

from lxml import etree

SNIPPET = 'tecas_website_blocks.s_tecas_news'
PAGE_VIEW_ID = 3645                     # website.accueil, the homepage
DROP_CLASS = 's_tecas_solutions'
ADD_CLASS = 's_tecas_news'

view = env['ir.ui.view'].sudo().browse(PAGE_VIEW_ID)
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')       # source first

rendered = env['ir.qweb'].sudo()._render(SNIPPET)
probe = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8'))
qweb_in_block = probe.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]")
if qweb_in_block:
    raise SystemExit('the rendered block still carries %d QWeb node(s); inserting '
                     'it would kill the page editor' % len(qweb_in_block))

for lang in langs:
    view_lang = view.with_context(lang=lang)
    root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
    wrap = root.xpath("//div[@id='wrap']")[0]
    qweb_before = len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"))
    changes = []

    for old in wrap.xpath("./section[contains(@class,'%s')]" % DROP_CLASS):
        old.getparent().remove(old)
        changes.append('removed .%s' % DROP_CLASS)

    if not wrap.xpath("./section[contains(@class,'%s')]" % ADD_CLASS):
        block = etree.fromstring(
            ('<root>%s</root>' % rendered).encode('utf-8')).find('section')
        # What the editor stamps on a dropped block; without them the builder
        # shows it as unnamed and offers no options.
        block.set('data-snippet', 's_tecas_news')
        block.set('data-name', 'Nos actualités')
        wrap.append(block)
        changes.append('added .%s at the end of #wrap' % ADD_CLASS)

    if not changes:
        print('%s: nothing to do' % lang)
        continue

    qweb_after = len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"))
    if qweb_after > qweb_before:
        env.cr.rollback()
        raise SystemExit('the block added %d QWeb node(s) under #wrap — page NOT written'
                         % (qweb_after - qweb_before))

    view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
    print('%s: %s' % (lang, '; '.join(changes)))

env.cr.commit()
print('committed — restart the web container so the compiled template cache follows')
