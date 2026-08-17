"""Put one address on the website — and only on the website.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/set_website_address.py

res.company is deliberately NOT touched. The company record holds QUARTIER AL
QODS / RUE 09 N°80 BERNOUSSI, which is what prints on invoices, quotes and
delivery notes; the client confirmed that the Polygone address is the
operational one and that the documents must keep the registered one. So the
address is written where the site shows it:

  * the footer's contact block, which until now rendered the company fields —
    the live footer holds a frozen copy of the block, so the copy is what gets
    rewritten (see refresh_footer_categories.py for the same pattern);
  * the "Localisation" line of the Contactez-Nous page.

The module template keeps reading res.company as a fallback, but prefers the
ir.config_parameter written here, so a freshly dropped footer says the same
thing as the one on the site today.
"""

import re

from lxml import etree

PARAM = 'tecas.website_address'
COMPANY_LABEL = 'TECAS ÉNERGIE SOLAIRE'
ADDRESS_LINES = [
    'Lot N°10, Lotissement Polygone',
    'Route des Zenata Km 10.5',
    'Zone Industrielle Aïn Sebaâ',
    'Casablanca, Maroc',
]
ONE_LINE = '%s – %s.' % (COMPANY_LABEL, ', '.join(ADDRESS_LINES))

report = []

env['ir.config_parameter'].sudo().set_param(PARAM, '\n'.join([COMPANY_LABEL] + ADDRESS_LINES))
report.append('set %s' % PARAM)

langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']
langs = sorted(langs, key=lambda code: code != 'en_US')       # source first

# --- the footer copy ------------------------------------------------------
footers = env['ir.ui.view'].sudo().search([('arch_db', 'like', 's_tecas_footer_contact')])
footers = footers.filtered(lambda v: not (v.key or '').startswith('tecas_website_blocks.'))
for view in footers:
    for lang in langs:
        view_lang = view.with_context(lang=lang)
        root = etree.fromstring(view_lang.arch_db.encode('utf-8'))
        changed = False
        for span in root.xpath("//ul[contains(@class,'s_tecas_footer_contact')]"
                               "/li[1]/span"):
            wanted = etree.fromstring(
                ('<span><strong>%s</strong><br/>%s</span>'
                 % (COMPANY_LABEL, '<br/>'.join(ADDRESS_LINES))).encode('utf-8'))
            if etree.tostring(span) == etree.tostring(wanted):
                continue
            span.getparent().replace(span, wanted)
            changed = True
        if changed:
            view_lang.write({'arch_db': etree.tostring(root, encoding='unicode')})
            report.append('footer %s (%s): address rewritten' % (view.id, lang))

# --- the pages ------------------------------------------------------------
# Matches the old wording wherever it was typed, rather than a single page:
# "route Zenata km 10.5, Ain Sebaa - lot 10 rdc. Zone industriel polygone".
OLD = re.compile(
    r'route\s+Zenata[^<]*?polygone[^<]*?(?:Casablanca[^<]*)?',
    re.I | re.S)
# The old line ended with a separate "<strong>Casablanca - Maroc</strong>" that
# the pattern above cannot swallow (a tag sits in the middle), and which the
# new address already says. Cleared in a second pass so the page does not read
# "…Casablanca, Maroc. Casablanca - Maroc".
TAIL = re.compile(
    r'(?:&amp;nbsp;|&nbsp;|\s)*<strong>\s*Casablanca\s*-\s*Maroc\s*</strong>',
    re.I)

for page in env['website.page'].sudo().search([]):
    view = page.view_id
    for lang in langs:
        view_lang = view.with_context(lang=lang)
        arch = view_lang.arch_db or ''
        if not (OLD.search(arch) or (ONE_LINE in arch and TAIL.search(arch))):
            continue
        new_arch = TAIL.sub('', OLD.sub(ONE_LINE, arch))
        if new_arch != arch:
            view_lang.write({'arch_db': new_arch})
            report.append('%s (%s): address line replaced' % (page.url, lang))

env.cr.commit()
print('\n--- website address ---')
for line in report or ['nothing to do']:
    print(' *', line)
print('\ncompany record left untouched:',
      env['res.company'].sudo().browse(1).street)
print('restart the web container so the compiled templates follow')
