"""Put the sliding brands strip on the homepage, just under the hero.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/add_brands_strip.py

Under the hero on purpose: the strip answers "what do you actually sell?" for
a visitor who has just landed, and it is the one place where seven familiar
logos do more work than a paragraph.

Same rules as the other page edits — a snippet template change does nothing to
a page that already holds a copy, each language is re-read inside the loop
because writing the source language regenerates the others, and nothing may
add a t-* attribute under #wrap.
"""

from lxml import etree

SNIPPET = 'tecas_website_blocks.s_tecas_brands'
PAGE_URL = '/'
ANCHOR_CLASS = 's_tecas_hero'      # insert right after the hero
ADD_CLASS = 's_tecas_brands'

page = env['website.page'].sudo().search([('url', '=', PAGE_URL)], limit=1)
if not page:
    raise SystemExit('homepage not found')
view = page.view_id
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')

rendered = env['ir.qweb'].sudo()._render(SNIPPET)
probe = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8'))
if probe.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"):
    raise SystemExit('the rendered strip carries QWeb; inserting it would kill the page editor')

report = []
for lang in langs:
    view_lang = view.with_context(lang=lang)
    root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
    wrap = root.xpath("//div[@id='wrap']")[0]
    if wrap.xpath("./section[contains(@class,'%s')]" % ADD_CLASS):
        report.append('%s: already there' % lang)
        continue

    qweb_before = len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"))
    block = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8')).find('section')
    block.set('data-snippet', 's_tecas_brands')
    block.set('data-name', 'Nos marques')

    anchors = wrap.xpath("./section[contains(@class,'%s')]" % ANCHOR_CLASS)
    if anchors:
        anchors[0].addnext(block)
        where = 'after .%s' % ANCHOR_CLASS
    else:
        wrap.insert(0, block)
        where = 'at the top of #wrap'

    if len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]")) > qweb_before:
        env.cr.rollback()
        raise SystemExit('the strip added QWeb under #wrap — page NOT written')

    view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
    report.append('%s: inserted %s' % (lang, where))

env.cr.commit()
print('\n--- brands strip ---')
for line in report:
    print(' *', line)
print('restart the web container so the compiled template follows')
