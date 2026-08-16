"""Drop the "Avis clients" block into the homepage, above the 3-steps block.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/add_reviews_to_homepage.py

Editing a snippet's template does not change a page that already exists:
dragging a snippet copies its rendered markup into the page arch, so a page is
only ever updated by rewriting that arch. This renders the block once and
splices it in, which is the same thing the editor does by hand.

Idempotent: a second run finds the block already there and stops.

The block is plain html, and that is not an accident — ir_ui_view's
distribute_branding() strips a node's editor branding as soon as a descendant
carries a t-* attribute, which would cost #wrap its data-oe-model and leave the
page with no drop zones at all. The guard below checks exactly that: no t-*
attribute may enter #wrap. (Calling distribute_branding() on a stored arch
proves nothing — it stamps no branding there even on a healthy page, which is
what makes the t-* count the honest test.)
"""

from lxml import etree

SNIPPET = 'tecas_website_blocks.s_tecas_reviews'
PAGE_VIEW_ID = 3645                     # website.accueil, the homepage
ANCHOR_CLASS = 's_tecas_steps'          # insert just before this block
SNIPPET_CLASS = 's_tecas_reviews'

view = env['ir.ui.view'].sudo().browse(PAGE_VIEW_ID)
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
# Source language first, and re-read the arch inside the loop: writing arch_db
# in en_US makes Odoo regenerate every other language from it term by term, so
# by the time the loop reaches fr_FR the block is already in there. Skipping
# that check is how the homepage first got TWO review sections.
langs = sorted(langs, key=lambda code: code != 'en_US')

if all(SNIPPET_CLASS in view.with_context(lang=lang).arch_db for lang in langs):
    print('already on the page in every language, nothing to do')
else:
    rendered = env['ir.qweb'].sudo()._render(SNIPPET)
    probe = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8'))
    qweb_in_block = probe.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]")
    if qweb_in_block:
        raise SystemExit('the rendered block still carries %d QWeb node(s); '
                         'inserting it would kill the page editor'
                         % len(qweb_in_block))

    # Each language holds its own copy of the arch. They are edited one by one
    # rather than by stamping one language's arch over the others, which would
    # replace every translated string on the page with the French one.
    for lang in langs:
        view_lang = view.with_context(lang=lang)
        if SNIPPET_CLASS in view_lang.arch_db:
            print('%s: already there (regenerated from the source language)' % lang)
            continue
        block = etree.fromstring(
            ('<root>%s</root>' % rendered).encode('utf-8')).find('section')
        # data-snippet/data-name are what the editor puts on a dropped block;
        # without them the builder shows it as unnamed and offers no options.
        block.set('data-snippet', 's_tecas_reviews')
        block.set('data-name', 'Avis clients')

        root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
        wrap = root.xpath("//div[@id='wrap']")[0]
        qweb_before = len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"))
        anchors = wrap.xpath("./section[contains(@class,'%s')]" % ANCHOR_CLASS)
        if anchors:
            anchor = anchors[0]
            block.tail = anchor.tail
            anchor.addprevious(block)
            where = 'before .%s' % ANCHOR_CLASS
        else:
            wrap.append(block)
            where = 'at the end of #wrap'

        new_arch = etree.tostring(root, encoding='unicode')

        # This insertion must not be what puts QWeb under #wrap. Whatever was
        # already there is someone else's problem (staging's homepage carries
        # some), and is reported rather than silently inherited or "fixed".
        qweb_after = len(wrap.xpath("descendant-or-self::*[@*[starts-with(name(), 't-')]]"))
        if qweb_after > qweb_before:
            env.cr.rollback()
            raise SystemExit('the block added %d QWeb node(s) under #wrap — page NOT written'
                             % (qweb_after - qweb_before))
        if qweb_before:
            print('%s: WARNING — %d pre-existing QWeb node(s) under #wrap; the page '
                  'editor may already show no drop zones' % (lang, qweb_before))

        view_lang.write({'arch_db': new_arch})
        print('%s: inserted %s, %d section(s) now'
              % (lang, where, new_arch.count('<section')))

    env.cr.commit()
    print('committed')
