"""Keep exactly one "Avis clients" block on the homepage.

Writing a translated arch_db in the SOURCE language (en_US) makes Odoo
regenerate the other languages from it, term by term. A loop that inserts a
block language by language therefore finds its own work already present when it
reaches the second language, and inserts it again — which is how the homepage
ended up with two review sections.

Languages are handled source-first here for the same reason: fixing en_US
rewrites fr_FR, so fr_FR has to be re-read afterwards rather than computed in
advance.
"""

from lxml import etree

PAGE_VIEW_ID = 3645
SNIPPET_CLASS = 's_tecas_reviews'

view = env['ir.ui.view'].sudo().browse(PAGE_VIEW_ID)
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')       # source first

for lang in langs:
    view_lang = view.with_context(lang=lang)
    root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
    blocks = root.xpath("//div[@id='wrap']/section[contains(@class,'%s')]" % SNIPPET_CLASS)
    if len(blocks) <= 1:
        print('%s: %d block(s), nothing to do' % (lang, len(blocks)))
        continue
    for extra in blocks[1:]:
        extra.getparent().remove(extra)
    view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
    print('%s: removed %d duplicate(s)' % (lang, len(blocks) - 1))

env.cr.commit()
for lang in langs:
    arch = view.with_context(lang=lang).arch_db
    print('%s: %d review block(s), %d section(s)'
          % (lang, arch.count('class="%s' % SNIPPET_CLASS), arch.count('<section')))
