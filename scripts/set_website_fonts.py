"""Set the site's typography: Inter Tight for titles, Manrope for body copy.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/set_website_fonts.py

TECAS_DRY=1 prints what it would write and rolls back.

Done through Odoo's own theme values rather than a font-family rule in the
module's css. That file — user_values.scss — is what the website editor reads
and writes, so the client can still change the fonts from Theme > Fonts
afterwards; a css override would fight whatever they picked and silently win.

Both families are added to 'google-fonts', which is the list Odoo loops over in
secondary_variables.scss to emit the @import. It builds a v1 request asking for
300/400/700 in both roman and italic; that was worth checking before relying on
it, since neither family is a classic static face — Inter Tight answers with
six faces, Manrope with three (it has no italics, and Google simply omits them
rather than failing the request).

This replaces Open Sans (body) and Oswald (headings).
"""

import os

DRY_RUN = os.environ.get('TECAS_DRY') == '1'

USER_VALUES = '/website/static/src/scss/options/user_values.scss'
VALUES = {
    # Quoted the way the file stores them: the value is written into a scss map
    # verbatim, so the quotes are part of it.
    'google-fonts': "('Inter Tight', 'Manrope')",
    'font': "'Manrope'",
    'headings-font': "'Inter Tight'",
}

Assets = env['website.assets'].sudo()

print('--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for key, value in VALUES.items():
    print(' * %-14s -> %s' % (key, value))

Assets.make_scss_customization(USER_VALUES, VALUES)

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted — the frontend bundle recompiles on the next page load')
