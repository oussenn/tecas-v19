"""Reshape the public category tree behind the "Nos Produits" menu.

Run it through the odoo shell:

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/restructure_product_categories.py

Set TECAS_DRY=1 in the container's environment to print the plan and roll back
instead of committing.

FAMILIES below is the whole of the client's catalogue plan, not a patch on it:
re-running the script is how the tree is brought back to that plan after
someone has moved things about in the backend.

The menu itself is generated from this tree by tecas_website_blocks'
models/tecas_autosync.py, so the shape below IS the menu: a family is a
top-level category, a sub-family one of its children, in sequence order.
Nothing a visitor cannot open is ever shown — either something published sits
under it, or it carries tecas_show_when_empty. Anything the script cannot place
is reported rather than guessed at.

The homepage grid is a separate, stricter list: HOMEPAGE_FAMILIES in
tecas_website_blocks/models/product_public_category.py. Rename a family here
and it must be renamed there too, or it drops out of the grid.

Categories are matched by name, not id, so the same script runs on staging
(whose ids differ) and can be re-run on prod without doing anything twice.
Existing categories are adopted and renamed wherever possible — that keeps
their id, and with it every /shop/category/<slug>-<id> url already in the
wild, since Odoo resolves the id and redirects to the new slug.
"""

import json
import os
import re
from datetime import datetime

DRY_RUN = os.environ.get('TECAS_DRY') == '1'
# The host's backups/ directory is not mounted in the web container, so the
# pre-change dump lands in /tmp and is copied out by whoever runs the script
# (docker cp tecas-web-19:<path> backups/). The path is printed below.
BACKUP_DIR = '/tmp'

# name          : the label the family or sub-family must end up with
# adopt         : existing category names to reuse for it, best first. Extra
#                 matches are merged into the first and deleted.
# products      : lower-case fragments matched against the names of the
#                 products sitting DIRECTLY in the parent family, which are
#                 then filed into this sub-family as well.
# nest          : existing categories to move underneath this one, untouched.
FAMILIES = [
    {
        'name': 'Panneaux Solaire',
        'adopt': ['PANNEAUX SOLAIRE', 'LES PANNEAUX SOLAIRE'],
        'sequence': 10,
        'children': [
            {'name': 'Jinko', 'products': ['jinko']},
            {'name': 'Canadian Solar', 'products': ['canadian']},
            {'name': 'Longi', 'products': ['longi']},
            {'name': 'Ecogreen', 'products': ['ecogreen']},
        ],
    },
    {
        'name': 'Onduleurs Solaires',
        'adopt': ['Onduleurs Solaire', 'ONDULEURS SOLAIRE', 'Onduleurs Solaires'],
        'sequence': 20,
        'children': [
            # Deye is the only hybrid published today and already sits here.
            {'name': 'Onduleurs Hybrides', 'adopt': ['Onduleurs Hybrides', 'Onduleur Hybride']},
            {'name': 'Onduleurs On-Grid',
             'adopt': ['ONDULEUR SOLAIRE ON-GRID', 'Onduleur On-Grid']},
            # "OFF-GRID HYBRIDE" is the old catch-all name for the off-grid
            # family (HPOWER, MUST); the hybrids proper have their own entry
            # above. Confirm the split with the client if a model is ambiguous.
            {'name': 'Onduleurs Off-Grid',
             'adopt': ['ONDULEUR SOLAIRE OFF-GRID HYBRIDE', 'Onduleur Off Grid']},
        ],
    },
    {
        'name': 'Batteries Solaires',
        'adopt': ['BATTERIES', 'BATTERIE GEL / Lithium', 'BATTERIE   GEL / Lithium'],
        'sequence': 30,
        'children': [
            {'name': 'Batteries Lithium', 'products': ['lithium', 'dyness']},
            {'name': 'Batteries Gel', 'products': ['gel']},
            {'name': 'Batteries AGM', 'products': ['agm']},
        ],
    },
    {
        # Two families, not one. "Pompes" is the pumps themselves; "Pompage
        # Solaire" below is the equipment that drives them. The first pass at
        # the client's brief read it as a rename of this family and merged the
        # two; unmerge_pumping() puts the name back before FAMILIES is applied.
        #
        # Keeping the id is what matters here: this branch carries 400+
        # references and the brand tree (ZINITH, PEDROLLO, WELL...), so every
        # /shop/category/pompes-383 link already in the wild still resolves.
        #
        # Nothing is published under any pump category and the client wants the
        # family announced anyway, so the whole branch is flagged
        # tecas_show_when_empty: it stays in the menu and its pages answer 200
        # with an empty grid instead of 404. Drop the flag once real pumps are
        # published and nothing else changes.
        'name': 'Pompes',
        'adopt': ['POMPES'],
        'sequence': 40,
        'show_when_empty': True,
        'children': [
            {'name': 'Pompes Solaires', 'show_when_empty': True},
            # Spare parts belong with the pumps, not with the pumping
            # equipment; nested back here now that the two are separate.
            {'name': 'Pompes Immergées', 'adopt': ['LES POMPE IMMERGEE', 'POMPES IMMERGEES'],
             'nest': ['PIECES DETACHEES POMPE'], 'show_when_empty': True},
            # Centrifugal pumps are surface pumps; kept as their own sub-level
            # so the client can move them if that reading is wrong.
            {'name': 'Pompes de Surface', 'nest': ['POMPES CENTRIFUGES'],
             'show_when_empty': True},
            {'name': 'Pompes Vide-Cave', 'show_when_empty': True},
        ],
    },
    {
        # The client's brief, exactly: three sub-categories, and no "Pompes"
        # among them. What belongs here is the equipment that makes a solar
        # pumping installation run — not the pumps, which have their own
        # family above.
        'name': 'Pompage Solaire',
        'sequence': 50,
        'show_when_empty': True,
        'children': [
            {'name': 'Variateurs de Vitesse', 'adopt': ['VARIATEUR DE VITESSE'],
             'show_when_empty': True},
            # An "armoire de pompage" IS a pre-wired control cabinet, so the
            # existing category becomes the one the client asked for rather than
            # sitting next to it as a duplicate. It left the coffrets family to
            # do so — say so if the client wants it in both.
            {'name': 'Coffrets de Commande Pré-câblés', 'adopt': ['ARMOIRE DE POMPAGE'],
             'show_when_empty': True},
            {'name': 'Accessoires de Pompage', 'show_when_empty': True},
        ],
    },
    {
        # New family. "Câble Solaire" and "Cable Electrique Souple" become two
        # of its sub-families instead of being copied into it: that is what the
        # client means by "retirer Cable Solaire des Accessoires pour éviter les
        # doublons", and it carries the 34 cable references (and their urls)
        # across untouched.
        'name': 'Câbles Électriques & Solaires',
        'sequence': 60,
        'show_when_empty': True,
        'children': [
            {'name': 'Câbles Solaires DC', 'adopt': ['Câble Solaire', 'CABLE SOLAIRE'],
             'show_when_empty': True},
            {'name': 'Câbles U-1000 R2V', 'show_when_empty': True},
            {'name': 'Câbles RV-K', 'show_when_empty': True},
            {'name': 'Câbles Souples',
             'adopt': ['Cable Electrique Souple', 'CABLE ELECTRIQUE SOUPLE'],
             'show_when_empty': True},
            # "Câbles Immergés" and "Accessoires de Câblage" were the client's
            # fifth and sixth; the menu carries four per family, so they are
            # folded into the family itself by DROP_INTO_PARENT below. Their
            # references stay on the site — only the sub-category goes.
        ],
    },
    {
        # Promoted out of Accessoires Solaires for the same reason as the
        # cables: a new top-level family plus the old sub-category would be the
        # duplicate the client is asking us to remove.
        'name': 'Structures & Fixations Solaires',
        'adopt': ['Structures et Fixations', 'STRUCTEUR EST FIXATIONS'],
        'sequence': 70,
        'show_when_empty': True,
        'children': [
            {'name': 'Rails de Montage', 'show_when_empty': True},
            {'name': 'Jumelage de Rails', 'show_when_empty': True},
            {'name': 'Clamps Solaires', 'show_when_empty': True},
            {'name': 'Massifs de Fixation', 'show_when_empty': True},
        ],
    },
    {
        'name': 'Coffrets & Protections Électriques',
        'adopt': ['Coffret de Protections AC/DC', 'COFFRET DE PROTECTIONS AC/DC'],
        'sequence': 80,
        'show_when_empty': True,
        'children': [
            # The two existing enclosure categories become the contents of the
            # client's "Coffrets Électriques" rather than three siblings of it.
            {'name': 'Coffrets Électriques', 'nest': ['COFFRET METAL BOX', 'COFFRET PVC'],
             'show_when_empty': True},
            {'name': 'Protections AC', 'show_when_empty': True},
            {'name': 'Protections DC', 'adopt': ['PROTECTIONS DC'], 'show_when_empty': True},
        ],
    },
    {
        'name': 'Éclairage Solaire',
        'adopt': ['ECLAIRAGE SOLAIRE'],
        'sequence': 90,
        'show_when_empty': True,
        'children': [
            {'name': 'Projecteurs Solaires', 'adopt': ['PROJECTEUR SOLAIRE'],
             'show_when_empty': True},
            {'name': 'Lampadaires Solaires', 'adopt': ['LAMPADAIRE SOLAIRE'],
             'show_when_empty': True},
            {'name': "Accessoires d'Éclairage Solaire", 'show_when_empty': True},
        ],
    },
    {
        # What is left of the old catch-all once the cables, the structures and
        # the DC protections have families of their own.
        'name': 'Accessoires Solaires',
        'adopt': ['ACCESSOIRES SOLAIRES'],
        'sequence': 110,
        'children': [
            {'name': 'Régulateurs de Charge', 'adopt': ['REGULATEURS DE CHARGE']},
            {'name': 'Boîte de Jonction', 'adopt': ['BOITE JONCTION']},
            {'name': 'Parafoudre', 'adopt': ['PARAFOUDRE']},
            # What was "Équipements & Solutions Énergétiques". That family is
            # retired from the site (HIDDEN_FROM_WEBSITE) and Accessoires
            # Solaires takes its place in the menu, carrying its four entries —
            # which also gives this family the sub-categories it was missing.
            # The first three above have nothing published and are not flagged,
            # so the menu shows exactly these four.
            {'name': 'Bornes de Recharge', 'show_when_empty': True},
            {'name': 'Stations Météo', 'show_when_empty': True},
            # Shortened: the old name was the only label in the column that
            # wrapped onto a second line, which is what made it scroll.
            {'name': 'Accessoires de Nettoyage',
             'adopt': ['Équipements de Nettoyage Solaire'], 'show_when_empty': True},
            {'name': 'Accessoires Techniques', 'show_when_empty': True},
        ],
    },
]

# Products sitting in a category they plainly do not belong to.
#
# "Câble Solaire" was the catalogue's only cable category for years, so every
# kind of cable was piled into it — and with it a Teltonika EV wall box, whose
# name happens to contain "avec câble 5m". Now that the client's sub-families
# exist, the obvious ones move down into them: it is what makes those
# sub-categories real rather than empty shells, and it stops an EV charger
# being the photo the site shows for "Câbles Souples".
#
# Names are matched WHOLE (after norm()), never as fragments, so a rule can
# never sweep up a neighbour; `contains` is the exception, for the two Teltonika
# references whose long names differ. Only unambiguous readings are listed —
# "Câbles Torsadés aluminium" and the ARVFV armoured cable are left where they
# are for the client to place.
REFILE = [
    {'to': 'Câbles U-1000 R2V', 'from': 'Câbles Solaires DC',
     'names': ['Cable U1000 R2V']},
    {'to': 'Câbles Électriques & Solaires', 'from': 'Câbles Solaires DC',
     'names': ['Cable Immergé']},
    {'to': 'Câbles Souples', 'from': 'Câbles Solaires DC',
     'names': ['Câble Souple']},
    {'to': 'Câbles Électriques & Solaires', 'from': 'Câbles Solaires DC',
     'names': ['Chemain de Câble']},
    {'to': 'Bornes de Recharge', 'from': 'Câbles Solaires DC',
     'contains': ['teltocharge']},
]

# Sub-categories folded back into their family: the products move up, the
# category itself is deleted. The menu carries four entries per family, and
# these were the fifth and sixth of a six-entry list.
DROP_INTO_PARENT = [
    ('Câbles Immergés', 'Câbles Électriques & Solaires'),
    ('Accessoires de Câblage', 'Câbles Électriques & Solaires'),
]

# Categories the client keeps in the catalogue but does not want on the site.
# Only ever set here — never cleared, so a category hidden by hand from the
# backend stays hidden.
#
# "Équipements & Solutions Énergétiques" is hidden rather than deleted: its four
# sub-categories now hang off Accessoires Solaires, so the family itself is
# empty, but keeping the record means the decision is one checkbox to undo.
HIDDEN_FROM_WEBSITE = (
    'Promo',
    'Équipements & Solutions Énergétiques',
    # Never part of the client's ten families. It only appeared in the menu
    # because a water heater was published, which made it browsable and gave
    # the panel an eleventh family on a third row.
    'Chauffe-eau Solaires',
)

# Families outside the client's plan. They keep their place; only their shouted
# names are brought in line with the ten above.
RENAMES = {
    'PROMO': 'Promo',
    'CHAUFFE-EAU SOLAIRES': 'Chauffe-eau Solaires',
    'CONVERTISSEURS DE TENSION': 'Convertisseurs de Tension',
}

report = []
Category = env['product.public.category'].sudo()
Product = env['product.template'].sudo()
langs = env['res.lang'].sudo().with_context(
    active_test=True).search([]).mapped('code') or ['en_US']


def norm(name):
    return re.sub(r'\s+', ' ', (name or '')).strip().upper()


def weight(categ):
    """Sort key: the fullest category of a name is the real one."""
    products = Product.with_context(active_test=False).search_count(
        [('public_categ_ids', 'in', categ.id)])
    return (-products, -len(categ.child_id), categ.id)


def index_categories():
    """{normalised name: categories}, fullest first.

    Names are not unique — a half-finished run leaves two "Batteries Gel" — so
    the index keeps every match and ensure() folds the extras into the one it
    keeps rather than letting a duplicate survive unnoticed.
    """
    index = {}
    for categ in Category.with_context(active_test=False).search([], order='id'):
        index.setdefault(norm(categ.name), []).append(categ)
    return {name: sorted(categs, key=weight) for name, categs in index.items()}


def set_name(categ, name):
    """Write the label in every installed language.

    name is a translated jsonb column: writing it in one language only would
    leave the menu showing the old shouted name in the other, since the panel
    is rendered once per language.
    """
    if all(categ.with_context(lang=lang).name == name for lang in langs):
        return False
    for lang in langs:
        categ.with_context(lang=lang).write({'name': name})
    return True


def merge_into(keeper, duplicate):
    """Empty a duplicate category into the one being kept, then drop it."""
    products = Product.with_context(active_test=False).search(
        [('public_categ_ids', 'in', duplicate.id)])
    if products:
        products.write({'public_categ_ids': [(4, keeper.id), (3, duplicate.id)]})
    if duplicate.child_id:
        duplicate.child_id.write({'parent_id': keeper.id})
    report.append('merged "%s" (%s) into "%s" (%s)%s'
                  % (duplicate.name, duplicate.id, keeper.name, keeper.id,
                     ', %d product(s) moved' % len(products) if products else ''))
    duplicate.unlink()


def ensure(spec, parent, sequence, index):
    """Adopt-or-create one category, renamed and reparented as specified."""
    # The target name leads the list so a second run adopts what the first one
    # produced instead of creating the whole tree again — the rename destroys
    # the old name this would otherwise match on.
    matches = []
    for candidate in [spec['name']] + spec.get('adopt', []):
        for categ in index.get(norm(candidate), []):
            if categ.exists() and categ not in matches:
                matches.append(categ)

    if matches:
        categ = matches[0]
        for duplicate in matches[1:]:
            # Drop it from the index before the merge — merge_into unlinks the
            # record, and reading .name off it afterwards would raise.
            index.get(norm(duplicate.name), []).remove(duplicate)
            merge_into(categ, duplicate)
        changes = []
        if set_name(categ, spec['name']):
            changes.append('renamed')
        if categ.parent_id.id != (parent.id if parent else False):
            categ.write({'parent_id': parent.id if parent else False})
            changes.append('moved under %s' % (parent.name if parent else 'the root'))
        if categ.sequence != sequence:
            categ.write({'sequence': sequence})
            changes.append('resequenced')
        wanted_flag = spec.get('show_when_empty', False)
        if categ.tecas_show_when_empty != wanted_flag:
            categ.write({'tecas_show_when_empty': wanted_flag})
            changes.append('shown while empty' if wanted_flag else 'hidden while empty')
        if changes:
            report.append('"%s" (%s): %s' % (spec['name'], categ.id, ', '.join(changes)))
    else:
        categ = Category.create({
            'name': spec['name'],
            'parent_id': parent.id if parent else False,
            'sequence': sequence,
            'tecas_show_when_empty': spec.get('show_when_empty', False),
        })
        for lang in langs:
            categ.with_context(lang=lang).write({'name': spec['name']})
        report.append('created "%s" (%s)%s'
                      % (spec['name'], categ.id,
                         ' under "%s"' % parent.name if parent else ''))

    # Forget every other name this record was indexed under. A rename
    # otherwise leaves the OLD name still pointing at it, and the next
    # family that lists that name adopts — or merges away — the wrong
    # record. That is exactly how "Pompes" and "Pompage Solaire" became
    # one category instead of two.
    for bucket in index.values():
        if categ in bucket:
            bucket.remove(categ)
    index[norm(spec['name'])] = [categ]
    return categ


def file_products(family, child, fragments):
    """File the family's own products into a sub-family by name.

    Only products sitting directly in the family are considered: a product
    already filed in another sub-family has been placed by hand or by an
    earlier run, and must not be dragged out of it.
    """
    loose = Product.with_context(active_test=False).search(
        [('public_categ_ids', 'in', family.id)])
    moved = Product.browse()
    for product in loose:
        name = (product.name or '').lower()
        if any(fragment in name for fragment in fragments) and child not in product.public_categ_ids:
            moved |= product
    if moved:
        moved.write({'public_categ_ids': [(4, child.id)]})
        report.append('"%s": %d product(s) filed — %s'
                      % (child.name, len(moved), ', '.join(moved.mapped('name'))))
    return moved


def backup_tree():
    rows = [{
        'id': categ.id,
        'name': {lang: categ.with_context(lang=lang).name for lang in langs},
        'parent_id': categ.parent_id.id or None,
        'sequence': categ.sequence,
        'product_ids': Product.with_context(active_test=False).search(
            [('public_categ_ids', 'in', categ.id)]).ids,
    } for categ in Category.with_context(active_test=False).search([], order='id')]
    menu_id = env['ir.config_parameter'].sudo().get_param('tecas.products_menu_id')
    menu = env['website.menu'].sudo().browse(int(menu_id)) if menu_id else env['website.menu']
    payload = {
        'taken': datetime.now().isoformat(timespec='seconds'),
        'categories': rows,
        'products_menu': [{'id': child.id, 'name': child.name, 'url': child.url,
                           'sequence': child.sequence} for child in menu.child_id],
    }
    path = os.path.join(
        BACKUP_DIR, 'public_categories_%s.json' % datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        report.insert(0, 'tree backed up to %s (%d categories)' % (path, len(rows)))
    except OSError as error:
        report.insert(0, 'BACKUP FAILED (%s) — nothing written' % error)
        raise


def unmerge_pumping():
    """Put the name "Pompes" back on the branch that holds the pumps.

    The first pass at the client's brief read "Pompage Solaire" as a rename of
    the existing "Pompes" family. It is not one: the client keeps the pumps
    themselves under Pompes, and Pompage Solaire is the equipment around them —
    drives, pre-wired control cabinets, accessories. Renaming merged two
    families into one and left the client's three sub-categories sitting beside
    four kinds of pump.

    Renaming it back, rather than moving the pumps into a new record, is what
    keeps the 400+ references, the brand tree and the existing urls attached to
    id 383. FAMILIES then builds "Pompage Solaire" fresh alongside it.

    Guarded on the branch still holding "Pompes Immergées", which is what makes
    this a one-off: the Pompage Solaire created below has no such child, so a
    second run does nothing.
    """
    for categ in Category.with_context(active_test=False).search(
            [('name', '=', 'Pompage Solaire')]):
        if any(norm(child.name) == norm('Pompes Immergées') for child in categ.child_id):
            set_name(categ, 'Pompes')
            report.append('"Pompage Solaire" (%s) renamed back to "Pompes" — they are two '
                          'separate families, and this is the one with the pumps in it'
                          % categ.id)


backup_tree()
unmerge_pumping()
index = index_categories()

for family_spec in FAMILIES:
    family = ensure(family_spec, None, family_spec['sequence'], index)
    for position, child_spec in enumerate(family_spec['children'], start=1):
        child = ensure(child_spec, family, position * 10, index)
        if child_spec.get('products'):
            file_products(family, child, child_spec['products'])
        for nested_name in child_spec.get('nest', []):
            for nested in index.get(norm(nested_name), []):
                if nested.exists() and nested.parent_id != child:
                    nested.write({'parent_id': child.id})
                    report.append('"%s" (%s) moved under "%s"'
                                  % (nested.name, nested.id, child.name))

for child_name, parent_name in DROP_INTO_PARENT:
    parent = (index.get(norm(parent_name)) or [None])[0]
    if not parent:
        report.append('DROP skipped: "%s" is missing' % parent_name)
        continue
    for categ in list(index.get(norm(child_name)) or []):
        if not categ.exists():
            continue
        index[norm(child_name)].remove(categ)
        # merge_into moves the products up and unlinks the category, so the
        # references stay on the site under the family instead of vanishing
        # with the sub-category.
        merge_into(parent, categ)

for spec in REFILE:
    target = (index.get(norm(spec['to'])) or [None])[0]
    source = (index.get(norm(spec['from'])) or [None])[0]
    if not target or not source:
        report.append('REFILE skipped: "%s" or "%s" is missing'
                      % (spec['to'], spec['from']))
        continue
    products = Product.with_context(active_test=False).search(
        [('public_categ_ids', 'in', source.id)])
    for product in products:
        name = norm(product.name)
        matched = (name in [norm(n) for n in spec.get('names', [])]
                   or any(fragment.upper() in name for fragment in spec.get('contains', [])))
        if not matched:
            continue
        product.write({'public_categ_ids': [(4, target.id), (3, source.id)]})
        report.append('"%s" (%s) moved from "%s" to "%s"'
                      % (product.name, product.id, source.name, target.name))

for old, new in RENAMES.items():
    for categ in index.get(norm(old), []):
        if categ.exists() and set_name(categ, new):
            report.append('"%s" (%s) renamed to "%s"' % (old, categ.id, new))

for hidden_name in HIDDEN_FROM_WEBSITE:
    for categ in index.get(norm(hidden_name), []):
        if categ.exists() and not categ.tecas_hide_from_website:
            categ.write({'tecas_hide_from_website': True})
            report.append('"%s" (%s) hidden from the website (catalogue untouched)'
                          % (categ.name, categ.id))

# Open the dropdown on hover. This is Odoo's own header option, so the client
# can still switch it off from the editor (Header → Navigation → "Dropdown on
# hover"); it lives in the database, which is why it is set here and not in the
# module — a git deploy would not carry it.
for website in env['website'].sudo().search([]):
    # Resolved the way the editor resolves it: a website that already has its
    # own copy of the view must have THAT copy activated. Switching on the
    # generic one instead changes nothing, because the copy keeps winning for
    # this website — website.viewref() hands back the generic record here.
    # filter_duplicate() reads website_id from the CONTEXT, not from the
    # recordset; without it every specific view is dropped as "another
    # website's" and only the generic one survives.
    views = env['ir.ui.view'].sudo().with_context(
        active_test=False, website_id=website.id).search([
        ('key', '=', 'website.header_hoverable_dropdown'),
        ('website_id', 'in', (False, website.id)),
    ]).filter_duplicate()
    for view in views.filtered(lambda v: not v.active):
        view.write({'active': True})
        report.append('hover-to-open enabled for website %s (view %s)' % (website.id, view.id))

# Families that still hold nothing published stay out of the menu; say so
# plainly instead of leaving the client to wonder where they went.
hidden, announced = [], []
for family_spec in FAMILIES:
    family = index[norm(family_spec['name'])][0]
    if not Product.search_count(
            [('public_categ_ids', 'child_of', family.id), ('is_published', '=', True)], limit=1):
        (announced if family.tecas_show_when_empty else hidden).append(family_spec['name'])

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for line in report:
    print(' *', line)
if announced:
    print('\nIn the menu with an empty page (flagged, nothing published yet): %s'
          % ', '.join(announced))
if hidden:
    print('\nNot in the menu, nothing published underneath: %s' % ', '.join(hidden))

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted')
