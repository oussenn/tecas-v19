"""Stop the Website > Analyse > Analytics page rendering a blank iframe.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/clear_stale_plausible.py

TECAS_DRY=1 prints what it would do and rolls back.

The page is Odoo's own client action `backend_dashboard`. It embeds

    https://plausible.io/share/<plausible_site>?auth=<plausible_shared_key>&embed=true

in a 1:1 iframe when both fields are set, and shows a "How to connect
Plausible?" panel when they are not.

This database was migrated off Odoo Online, and it came away with the Plausible
credentials that odoo.com had provisioned for it:

    plausible_site       = tecas.odoo.com-d174
    plausible_shared_key = 4PjHshqNKWjwxOwcbDsPj

That shared dashboard belongs to Odoo's own SaaS account and answers 404 from
here (plausible.io itself answers 200, so it is the link that is dead, not the
network). The iframe therefore loads a 404 page — which, being an iframe, shows
as a tall blank area with no error anywhere: exactly what was reported.

Clearing the two dead fields is the fix. It does not remove analytics — there
were none to remove, since nothing has been reporting to that site since the
migration — it makes the page fall back to the panel that tells you how to
connect a real Plausible account. Put a genuine site name and shared key in
Website > Configuration > Settings > Traffic and the iframe comes back.

The old values are printed before they go, so they can be put back.
"""

import os

DRY_RUN = os.environ.get('TECAS_DRY') == '1'
SHARE_URL = 'https://plausible.io/share/%s?auth=%s&embed=true&theme=system'

report = []

for website in env['website'].sudo().search([]):
    site, key = website.plausible_site, website.plausible_shared_key
    if not (site or key):
        report.append('website %s (%s): no Plausible settings, nothing to do'
                      % (website.id, website.name))
        continue
    report.append('website %s (%s): clearing site=%r shared_key=%r'
                  % (website.id, website.name, site, key))
    report.append('    the dashboard was embedding ' + (SHARE_URL % (site, key)))
    if not DRY_RUN:
        website.write({'plausible_site': False, 'plausible_shared_key': False})

# Not touched, but worth knowing about while you are in here: the Google
# Analytics property on this site is a Universal Analytics id (UA-...), and
# Universal Analytics stopped collecting data on 1 July 2023. The tag still
# loads googletagmanager.com on every page and reports nothing. Replacing it
# with a GA4 measurement id (G-...) or clearing it is a separate decision — it
# changes what the public site loads — so it is left to the client.
for website in env['website'].sudo().search([]):
    ga = website.google_analytics_key or ''
    if ga.upper().startswith('UA-'):
        report.append('website %s: google_analytics_key is %r — Universal Analytics, '
                      'dead since 2023-07-01, still loaded on every page'
                      % (website.id, ga))

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for line in report:
    print(' *', line)

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted')
