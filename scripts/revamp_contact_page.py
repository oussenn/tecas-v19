"""Bring the Contactez-Nous hero back to a sane size and calm the form band.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/revamp_contact_page.py

The banner carried pt256 pb216 — nearly 500px of padding on top of a 48px
headline — so the page opened on a photo and nothing else: on a laptop the
form was two screens down. It also shipped a button labelled "Envoyez votre
de", a headline cut into two hard-coded font sizes, and a translucent box so
pale that white text sat on a busy photograph.

Changes, all on the page arch (a snippet template edit would not touch a page
that already holds a copy):
  * padding down to pt96 pb96, box narrowed to two thirds and darkened enough
    to read against the photo;
  * headline freed of its inline font sizes, so it follows the theme and
    scales on a phone;
  * the button says what it does and still points at the form anchor;
  * the form band leaves o_cc3 — a saturated blue that belongs to no part of
    this site — for the light palette the rest of the pages use.

Idempotent: every step checks the current value first.
"""

from lxml import etree

PAGE_URL = '/demande-devis'
CTA_LABEL = 'Envoyez votre demande'

page = env['website.page'].sudo().search([('url', '=', PAGE_URL)], limit=1)
if not page:
    raise SystemExit('%s not found' % PAGE_URL)
view = page.view_id
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')       # source first

report = []
for lang in langs:
    view_lang = view.with_context(lang=lang)
    root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
    wrap = root.xpath("//div[@id='wrap']")[0]
    changed = []

    banners = wrap.xpath("./section[contains(@class,'s_banner')]")
    if banners:
        banner = banners[0]
        classes = (banner.get('class') or '').split()
        resized = [c for c in classes if not c.startswith(('pt', 'pb'))] + ['pt96', 'pb96']
        if classes != resized:
            banner.set('class', ' '.join(resized))
            changed.append('banner padding')

        for box in banner.xpath(".//div[contains(@class,'jumbotron')]"):
            box_classes = (box.get('class') or '').split()
            narrowed = ['col-lg-8' if c == 'col-lg-12' else c for c in box_classes]
            if box_classes != narrowed:
                box.set('class', ' '.join(narrowed))
                changed.append('box width')
            # Legibility over a photograph, not decoration: the old fill was
            # 18% blue, which left white text competing with the image.
            style = box.get('style') or ''
            if 'rgba(10, 37, 64, 0.62)' not in style:
                box.set('style', 'background-color: rgba(10, 37, 64, 0.62);')
                changed.append('box contrast')

        for link in banner.xpath(".//a[contains(@class,'btn')]"):
            label = ''.join(link.itertext()).strip()
            if label and label != CTA_LABEL:
                for child in list(link):
                    link.remove(child)
                link.text = CTA_LABEL
                changed.append('button label (%r)' % label)

    for section in wrap.xpath("./section[contains(@class,'o_cc3')]"):
        if 's_website_form' in etree.tostring(section, encoding='unicode'):
            section.set('class', (section.get('class') or '').replace('o_cc3', 'o_cc1'))
            changed.append('form band palette')

    # Headings across the page were typed at fixed pixel sizes — 62px, 48px,
    # 36px — which is why everything reads oversized and why nothing shrinks on
    # a phone. Dropping the inline size hands them back to the theme, where h1
    # and h2 are already defined and responsive.
    for heading in wrap.xpath(".//h1|.//h2|.//h3"):
        for node in heading.xpath("descendant-or-self::*[@style]"):
            style = node.get('style') or ''
            if 'font-size' not in style:
                continue
            kept = '; '.join(part.strip() for part in style.split(';')
                             if part.strip() and 'font-size' not in part)
            if kept:
                node.set('style', kept)
            else:
                del node.attrib['style']
            changed.append('heading sizes')
        # An empty <font> renders nothing but keeps its line box, which is
        # where half the gap under these titles came from.
        for empty in heading.xpath(".//font"):
            if not (empty.text or '').strip() and not len(empty):
                empty.getparent().remove(empty)
                changed.append('empty heading node')

    if changed:
        view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
        report.append('%s: %s' % (lang, ', '.join(sorted(set(changed)))))

env.cr.commit()
print('\n--- contact page ---')
for line in report or ['nothing to do']:
    print(' *', line)
print('restart the web container so the compiled template follows')
