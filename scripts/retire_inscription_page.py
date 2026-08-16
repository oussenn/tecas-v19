"""Retire the standalone "Formulaire d'inscription": the form lives on Contactez-Nous.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/retire_inscription_page.py

The two pages carried the same questionnaire, but not to the same place:
/demande-devis posts to **crm.lead**, so a submission becomes a lead someone
follows up; /formulaire-d-inscription posts to **mail.mail**, so it only sends
a message. Keeping the second one live meant some prospects filled in the form
that generates no lead at all.

So the menu entry goes, the page is unpublished, and a 301 sends the url to
/demande-devis — links printed on a flyer or shared in a message keep working
and land on the form that actually records the request. Everything here is
reversible: republish the page and delete the redirect.
"""

MENU_LABEL = 'Formulaire'
OLD_URL = '/formulaire-d-inscription'
NEW_URL = '/demande-devis'

report = []

menus = env['website.menu'].sudo().search([('url', '=', OLD_URL)])
menus |= env['website.menu'].sudo().search([('name', 'ilike', MENU_LABEL)])
for menu in menus:
    report.append('removed the menu entry "%s" (%s)' % (menu.name, menu.id))
    menu.unlink()

page = env['website.page'].sudo().search([('url', '=', OLD_URL)], limit=1)
if page and page.is_published:
    page.write({'is_published': False})
    report.append('unpublished the page %s (%s)' % (OLD_URL, page.id))

Rewrite = env['website.rewrite'].sudo()
if not Rewrite.search([('url_from', '=', OLD_URL)]):
    Rewrite.create({
        'name': 'Formulaire d\'inscription vers la page de contact',
        'redirect_type': '301',
        'url_from': OLD_URL,
        'url_to': NEW_URL,
        'website_id': env['website'].sudo().search([], limit=1).id,
    })
    report.append('added a 301 from %s to %s' % (OLD_URL, NEW_URL))

env.cr.commit()
print('\n--- inscription page ---')
for line in report or ['nothing to do']:
    print(' *', line)
