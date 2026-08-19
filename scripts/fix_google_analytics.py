"""Point Odoo at the Google Analytics property that is actually collecting.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/fix_google_analytics.py

TECAS_DRY=1  print what would change and roll back.

The site was loading TWO Google tags on every page:

  * UA-130624825-1, from Odoo's own Google Analytics setting. Universal
    Analytics stopped processing data on 1 July 2024, so that request has been
    fetching a script for a dead property for over a year.
  * G-QD2YZRRT6M, a GA4 tag pasted by hand into the website's <head> code.
    This is the one the client set up and the one with the data in it.

This moves the GA4 id into the supported setting and takes the hand-pasted
copy out, leaving exactly one tag on the page. Same property, same data, one
script instead of two, and nothing left pointing at a property Google switched
off. The Meta Pixel and the Facebook domain verification in the same field are
left untouched.

Doing only half of this would be worse than doing none: the id in the setting
AND the pasted snippet both load gtag, and Google counts the page twice.
"""

import os
import re

DRY_RUN = os.environ.get('TECAS_DRY') == '1'

# The block to lift out: the loader script and the inline config that follows
# it, with the comment Google's own instructions tell you to paste.
GTAG_BLOCK = re.compile(
    r'[ \t]*<!--\s*Google tag \(gtag\.js\)\s*-->\s*'
    r'<script[^>]*googletagmanager\.com/gtag/js\?id=(G-[A-Z0-9]+)[^>]*>\s*</script>\s*'
    r'<script>.*?gtag\(\s*[\'"]config[\'"].*?</script>\s*',
    re.S | re.I)

website = env['website'].sudo().browse(1)
head = website.custom_code_head or ''

match = GTAG_BLOCK.search(head)
if not match:
    raise SystemExit(
        'No hand-pasted gtag block found in the head code — refusing to guess.\n'
        'Head code starts:\n%s' % head[:300])

measurement_id = match.group(1)
new_head = GTAG_BLOCK.sub('', head, count=1)

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
print(' * analytics key : %s  ->  %s' % (website.google_analytics_key or '(none)', measurement_id))
print(' * head code     : %d  ->  %d bytes' % (len(head), len(new_head)))
print(' * kept in head  : %s' % ', '.join(
    name for name, needle in (('Meta Pixel', 'fbevents.js'),
                              ('Facebook domain verification', 'facebook-domain-verification'))
    if needle in new_head) or '-')
print(' * gtag loaders left in head: %d'
      % len(re.findall(r'googletagmanager\.com/gtag/js', new_head)))

if not DRY_RUN:
    website.write({
        'google_analytics_key': measurement_id,
        'custom_code_head': new_head,
    })
    env.cr.commit()
    print('\ncommitted')
else:
    env.cr.rollback()
    print('\nrolled back')
