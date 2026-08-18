"""Give every public category a picture, taken from the products inside it.

    docker exec -i tecas-web-19 odoo shell -d tecas19 \
        -c /etc/odoo/odoo.conf --no-http < scripts/set_category_images.py

TECAS_DRY=1  print the plan and roll back.
TECAS_FORCE=1 replace pictures that are already set (otherwise they are left
              alone — a category the client has dressed by hand must survive a
              re-run).

The image goes on the category RECORD, not into the website module: the tiles,
the sub-category strip and the shop's own listings all read
product.public.category.image_1920, so writing it there is what puts a picture
on the site, and the client can then change any of them from the backend in two
clicks without touching code.

Where the picture comes from, in order:

  1. a product in the category itself — published ones first, since those are
     the ones the client has chosen to show;
  2. failing that, a product further down the branch;
  3. failing that, the nearest ancestor's stock of product photos — "or
     something similar", which is how "Câbles RV-K" (no products yet) ends up
     showing a cable rather than a grey placeholder.

Siblings are dealt DIFFERENT photos out of that shared stock wherever there are
enough to go round. They are displayed side by side in the sub-category strip,
and four identical thumbnails under four different names read as a bug.
"""

import os
import re

DRY_RUN = os.environ.get('TECAS_DRY') == '1'
FORCE = os.environ.get('TECAS_FORCE') == '1'
# Clear the pictures that were BORROWED on an earlier run (the categories with
# no photo of their own) and pick them again. Use it after changing how
# borrowing chooses; it never touches a category that can dress itself, so the
# client's own artwork on a real category is safe.
REDO_BORROWED = os.environ.get('TECAS_REDO_BORROWED') == '1'

# Categories that must stay blank rather than wear a neighbour's photo. The
# energy-equipment family holds exactly one product with a picture — a Teltonika
# EV wall box — so without this it would end up standing for "Stations Météo"
# and "Équipements de Nettoyage Solaire" too, which is worse than a blank.
NO_BORROW = (
    'Stations Météo',
    'Équipements de Nettoyage Solaire',
    'Accessoires Techniques',
)

# Word stems too common in this catalogue to say anything about a product:
# nearly every reference is "solaire", so matching on it would match everything.
STOP_STEMS = {'SOLA', 'POUR', 'AVEC', 'DANS'}

Category = env['product.public.category'].sudo().with_context(active_test=False)
Product = env['product.template'].sudo()

report = []
skipped = []
unresolved = []


def candidates(categ):
    """Product ids under `categ` that have a picture, best first.

    Published first: those are the products a visitor can actually reach, so
    the category ends up wearing something the site itself shows. Ordered by id
    inside each group, so the same run twice picks the same photo.
    """
    domain = [('public_categ_ids', 'child_of', categ.id), ('image_512', '!=', False)]
    published = Product.search(domain + [('is_published', '=', True)], order='id').ids
    rest = [pid for pid in Product.search(domain, order='id').ids if pid not in published]
    return published + rest


def stems(text):
    """Four-letter word stems, which is enough to make "Pompes" meet "POMPE
    IMMERGEE" and "Câbles" meet "Câble Rigide" without a stemmer."""
    words = re.findall(r'[^\W\d_]{4,}', (text or '').upper(), re.UNICODE)
    return {word[:4] for word in words} - STOP_STEMS


def by_affinity(categ, pool):
    """Re-order a BORROWED pool so the closest-reading photo comes first.

    Borrowing takes whatever the family above has, and the family above is not
    always homogeneous: the only published products under "Pompage Solaire" are
    variable-speed drives, so "Pompes de Surface" was being given a picture of
    a drive. Preferring a product whose name shares a word with the category's
    finds an actual pump instead. Ties keep the pool's own order, so the result
    is still the same on every run.
    """
    wanted = stems(categ.name)
    if not wanted:
        return pool
    ranked = sorted(
        enumerate(pool),
        key=lambda pair: (-len(wanted & stems(Product.browse(pair[1]).name)), pair[0]))
    return [product_id for _, product_id in ranked]


def source_for(pool, taken):
    """Pick a photo out of `pool` that a sibling is not already wearing."""
    for product_id in pool:
        if product_id not in taken:
            return product_id
    if not pool:
        return None
    # Fewer photos than sub-categories, so one has to be worn twice. Carry on
    # round the pool rather than falling back on the first every time: with two
    # photos and five sub-categories that is A B A B A, not A B A A A.
    return pool[len(taken) % len(pool)]


categories = Category.search([], order='parent_path')
own_pool = {categ.id: candidates(categ) for categ in categories}

# {parent id: photos already given to its children}, so siblings differ.
taken_under = {}

if REDO_BORROWED:
    stale = categories.filtered(lambda c: not own_pool[c.id] and c.image_1920)
    # Cleared even on a dry run — the run ends in a rollback, and leaving the
    # old pictures in place would make the preview show "nothing to do" for
    # every category the redo is meant to revisit.
    stale.write({'image_1920': False})
    report.append('cleared %d borrowed picture(s) to pick them again: %s'
                  % (len(stale), ', '.join(stale.mapped('name'))))

# Pass 1 — everything that can dress itself out of its own branch. Done first
# so that pass 2 knows which photos are already spoken for.
still_bare = Category.browse()
for categ in categories:
    if categ.image_1920 and not FORCE:
        skipped.append(categ.name)
        continue
    pool = own_pool[categ.id]
    if not pool:
        still_bare |= categ
        continue
    taken = taken_under.setdefault(categ.parent_id.id or 0, set())
    product_id = source_for(pool, taken)
    taken.add(product_id)
    product = Product.browse(product_id)
    if not DRY_RUN:
        categ.write({'image_1920': product.image_1920})
    report.append('"%s" (%s) <- %s (%s)' % (categ.name, categ.id, product.name, product.id))

# Pass 2 — the empty ones borrow from the nearest branch above them.
for categ in still_bare:
    if categ.name in NO_BORROW:
        unresolved.append('%s (%s) — must not borrow' % (categ.name, categ.id))
        continue
    parent = categ.parent_id
    pool, borrowed_from = [], None
    while parent and not pool:
        pool, borrowed_from = own_pool.get(parent.id) or [], parent
        parent = parent.parent_id
    if not pool:
        unresolved.append('%s (%s)' % (categ.name, categ.id))
        continue
    pool = by_affinity(categ, pool)
    taken = taken_under.setdefault(categ.parent_id.id or 0, set())
    product_id = source_for(pool, taken)
    taken.add(product_id)
    product = Product.browse(product_id)
    if not DRY_RUN:
        categ.write({'image_1920': product.image_1920})
    report.append('"%s" (%s) <- %s (%s), borrowed from "%s"'
                  % (categ.name, categ.id, product.name, product.id, borrowed_from.name))

print('\n--- %s ---' % ('DRY RUN' if DRY_RUN else 'APPLIED'))
for line in report:
    print(' *', line)
print('\n%d category picture(s) set, %d left as they were' % (len(report), len(skipped)))
if unresolved:
    print('\nNo photo anywhere in the catalogue, left blank — these need a picture '
          'from the client:\n   %s' % '\n   '.join(unresolved))

if DRY_RUN:
    env.cr.rollback()
    print('\nrolled back')
else:
    env.cr.commit()
    print('\ncommitted')
