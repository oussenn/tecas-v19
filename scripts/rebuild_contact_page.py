# -*- coding: utf-8 -*-
"""Rebuild /demande-devis as the contact page the client asked for: the form,
the ways to reach TECAS, and the map underneath.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/rebuild_contact_page.py

TECAS_DRY=1  print what would change and roll back.

The page it replaces was five sections long — a banner, a title, a strip of
process steps, a photo — with the form at the bottom. Everything above the form
is dropped: a visitor who has clicked "Contactez-Nous" has already decided, and
the page's only job from there is to take the message.

WHAT IS PRESERVED, and why it matters more than the layout: the form still
posts to /website/form/ as a crm.lead, still carries the hidden team_id that
routes the lead to the right sales team, and still uses the same field names —
name, email_from, phone, "Sujet", "Vous êtes :". Leads that arrive tomorrow
therefore land exactly where yesterday's did. Only the dressing changed.

The old arch is written to backups/ before anything else, because this page was
built by hand in the website editor and there is no other copy of it.
"""

import os
from datetime import datetime

from lxml import etree

DRY_RUN = os.environ.get('TECAS_DRY') == '1'

PAGE_URL = '/demande-devis'
BACKUP_DIR = os.environ.get("TECAS_BACKUP_DIR", "/opt/tecas-v19/backups")
SOURCE_LANG = 'en_US'

# The company's details, worded as the footer words them so the site says the
# same thing twice rather than two slightly different things.
ADDRESS = ('Lot N°10, Lotissement Polygone, Route des Zenata Km 10.5,'
           ' Zone Industrielle Aïn Sebaâ, Casablanca, Maroc')
PHONE_LABEL = '+212 520 854 141'
PHONE_HREF = 'tel:+212520854141'
WHATSAPP_LABEL = '+212 664 276 055'
WHATSAPP_HREF = ('https://api.whatsapp.com/send/?phone=212664276055'
                 '&amp;text&amp;type=phone_number&amp;app_absent=0')
EMAIL = 'info@tecas.ma'
# Google's embed endpoint, which needs no API key — unlike the Maps snippet in
# the editor, which renders a "configure your key" placeholder without one.
MAP_QUERY = ('Lot+N%C2%B010+Lotissement+Polygone+Route+des+Zenata+Km+10.5'
             '+A%C3%AFn+Seba%C3%A2+Casablanca+Maroc')
MAP_SRC = ('https://maps.google.com/maps?q=%s&amp;t=m&amp;z=15&amp;ie=UTF8&amp;output=embed'
           % MAP_QUERY)


def field(name, slug, placeholder, label, *, tag='input', input_type='text',
          width='col-lg-6', required='s_website_form_required',
          fill_with=None, rows=None, options=None):
    """One field of Odoo's form snippet, with its label hidden.

    The full label/input structure is kept — d-none on the label rather than no
    label at all — because that is what the form builder writes when someone
    chooses to hide labels in the editor. Anything simpler renders the same but
    stops the client editing the field from the editor afterwards.
    """
    # A readable, stable id: the label has to point at the input even though
    # it is hidden, and a field name like "Vous êtes :" cannot be one.
    node_id = 'tecas_ct_%s' % slug
    fill = ' data-fill-with="%s"' % fill_with if fill_with else ''
    if options is not None:
        choices = ''.join('<option value="%s">%s</option>' % (o, o) for o in options)
        control = ('<select class="form-select s_website_form_input" name="%s" '
                   'required="1" id="%s"><option value="">%s</option>%s</select>'
                   % (name, node_id, placeholder, choices))
        data_type = 'selection'
    elif tag == 'textarea':
        control = ('<textarea class="form-control s_website_form_input" name="%s" '
                   'required="1" placeholder="%s" id="%s" rows="%s"/>'
                   % (name, placeholder, node_id, rows or 6))
        data_type = 'text'
    else:
        control = ('<input type="%s" class="form-control s_website_form_input" name="%s" '
                   'required="1" placeholder="%s" id="%s"%s/>'
                   % (input_type, name, placeholder, node_id, fill))
        data_type = 'char'
    return """
                        <div class="s_website_form_field mb-3 col-12 %s %s" data-type="%s" data-name="Field">
                            <div class="row s_col_no_resize s_col_no_bgcolor">
                                <label class="d-none col-form-label col-sm-auto s_website_form_label" style="width: 200px" for="%s">
                                    <span class="s_website_form_label_content">%s</span>
                                    <span class="s_website_form_mark"> *</span>
                                </label>
                                <div class="col-sm">%s</div>
                            </div>
                        </div>""" % (width, required, data_type, node_id, label, control)


def contact_item(icon, label, value):
    return """
                        <div class="s_tecas_ct_item mb-4">
                            <span class="s_tecas_ct_icon"><i class="fa %s" aria-hidden="true"/></span>
                            <div>
                                <p class="s_tecas_ct_label">%s</p>
                                <p class="s_tecas_ct_value">%s</p>
                            </div>
                        </div>""" % (icon, label, value)


FIELDS = ''.join([
    # crm.lead.name is required by the model, and it is what the client's
    # pipeline shows as the lead's title — so it holds the person's name, as it
    # did on the old form. Splitting it into Prénom/Nom would put half of it in
    # the lead's description and leave the pipeline reading "Ennaciri".
    field('name', 'name', 'Nom et prénom', 'Nom',
          required='s_website_form_model_required'),
    field('phone', 'phone', 'Numéro de téléphone', 'Téléphone', fill_with='phone'),
    field('email_from', 'email', 'Adresse email', 'Email',
          input_type='email', fill_with='email'),
    field('Vous êtes :', 'profile', 'Vous êtes ?', 'Vous êtes :',
          required='s_website_form_custom s_website_form_required',
          options=('Revendeur', 'Installateur', 'Client final')),
    field('Sujet', 'message', 'Votre message', 'Sujet', tag='textarea',
          width='col-lg-12',
          required='s_website_form_custom s_website_form_required', rows=6),
])

BODY = """
            <section class="s_tecas_ct_head pt40 pb40" data-name="En-tête Contact">
                <div class="container text-center">
                    <h1 class="s_tecas_ct_title">Contactez-nous</h1>
                    <p class="s_tecas_ct_crumb"><a href="/">Accueil</a> / <strong>Contact</strong></p>
                </div>
            </section>
            <section class="s_tecas_ct_main pt56 pb40" data-name="Contact">
                <div class="container">
                    <div class="row g-5">
                        <div class="col-lg-5">
                            <h2 class="s_tecas_ct_lead mb-5">Demandez votre devis<span>gratuit et personnalisé</span></h2>%(items)s
                        </div>
                        <div class="col-lg-7">
                            <section class="s_website_form s_tecas_ct_card" data-vcss="001" data-snippet="s_website_form" data-name="Form">
                                <form action="/website/form/" method="post" enctype="multipart/form-data" class="o_mark_required" data-mark="*" data-pre-fill="true" data-success-mode="message" data-success-page="/telechargement" data-model_name="crm.lead">
                                    <div class="s_website_form_rows row s_col_no_bgcolor">%(fields)s
                                        <div class="mb-0 py-2 col-12 s_website_form_submit" data-name="Submit Button">
                                            <a href="#" role="button" class="btn btn-lg s_tecas_btn_orange s_website_form_send">Envoyer</a>
                                            <span id="s_website_form_result"/>
                                        </div>
                                        <div class="s_website_form_field mb-0 col-12 s_website_form_dnone" data-name="Field">
                                            <div class="row s_col_no_resize s_col_no_bgcolor">
                                                <label class="col-form-label col-sm-auto s_website_form_label" style="width: 200px">
                                                    <span class="s_website_form_label_content"/>
                                                </label>
                                                <div class="col-sm">
                                                    <input type="hidden" class="form-control s_website_form_input" name="team_id" value="7"/>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </form>
                            </section>
                        </div>
                    </div>
                </div>
            </section>
            <section class="s_tecas_ct_map pb64" data-name="Carte">
                <div class="container">
                    <iframe src="%(map)s" title="TECAS Énergie Solaire — Aïn Sebaâ, Casablanca" loading="lazy" referrerpolicy="no-referrer-when-downgrade" allowfullscreen="allowfullscreen"/>
                </div>
            </section>
        """ % {
    'items': ''.join([
        contact_item('fa-map-marker', 'Adresse', ADDRESS),
        contact_item('fa-phone', 'Numéro de téléphone',
                     '<a href="%s">%s</a>' % (PHONE_HREF, PHONE_LABEL)),
        contact_item('fa-whatsapp', 'WhatsApp',
                     '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                     % (WHATSAPP_HREF, WHATSAPP_LABEL)),
        contact_item('fa-envelope', 'Adresse Email',
                     '<a href="mailto:%s">%s</a>' % (EMAIL, EMAIL)),
    ]),
    'fields': FIELDS,
    'map': MAP_SRC,
}

page = env['website.page'].sudo().search([('url', '=', PAGE_URL)], limit=1)
if not page:
    raise SystemExit('no page at %s' % PAGE_URL)
view = page.view_id
langs = env['res.lang'].sudo().with_context(active_test=True).search([]).mapped('code')
langs = set(langs or []) | {SOURCE_LANG}

old = view.with_context(lang=SOURCE_LANG).arch_db
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = os.path.join(BACKUP_DIR, 'demande-devis_%s.html' % stamp)
try:
    with open(backup, 'w', encoding='utf-8') as handle:
        handle.write(old)
except OSError as error:            # a backup that cannot be written is a stop
    raise SystemExit('could not write %s: %s' % (backup, error))

# Replace the CONTENTS of #wrap rather than rebuilding the whole arch: the
# t-name, the t-call to website.layout and whatever classes the editor left on
# the wrapper are the page's plumbing, and none of it is ours to reinvent.
root = etree.fromstring(old.encode('utf-8'))
wrap = root.xpath("//div[@id='wrap']")
if not wrap:
    raise SystemExit('no #wrap in the page arch — refusing to guess')
wrap = wrap[0]
for child in list(wrap):
    wrap.remove(child)
wrap.text = None
for node in etree.fromstring('<root>%s</root>' % BODY):
    wrap.append(node)
new_arch = etree.tostring(root, encoding='unicode')

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
print(' * page %s, view %s' % (page.id, view.id))
print(' * old arch saved to %s (%d bytes)' % (backup, len(old)))
print(' * new arch: %d bytes, %d section(s), %d form field(s)'
      % (len(new_arch), new_arch.count('<section'), new_arch.count('s_website_form_field')))
print(' * languages written: %s' % ', '.join(sorted(langs)))

if not DRY_RUN:
    for lang in sorted(langs, key=lambda code: code != SOURCE_LANG):
        view.with_context(lang=lang).write({'arch_db': new_arch})
    env.cr.commit()
    print('\ncommitted')
else:
    env.cr.rollback()
    print('\nrolled back')
