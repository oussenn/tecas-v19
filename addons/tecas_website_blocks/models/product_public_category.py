import re

from odoo import api, fields, models
from odoo.fields import Domain

from .tecas_autosync import _has_published_product, _relevant_categories

# The homepage grid, in the order the client wants it read: what an installer
# buys first leads, and the rest follows the job down the roof.
#
# It is a PREFERENCE list, not a fixed grid. A family only gets a tile once
# something under it is published — a tile leading to an empty page is worse
# than no tile — so the list falls through to the next name until seven are
# filled. Pompage and Éclairage are the two most searched families in Morocco
# and hold no published product today; they take their place by themselves the
# day one is published, with no code change.
#
# Matched on name rather than id so the order survives a category being
# recreated, and so it reads as a rule instead of a row of magic numbers.
HOMEPAGE_FAMILIES = (
    # The five the client asked for by name, plus pumping and lighting — the
    # two most searched in Morocco. Those seven come first because there are
    # more qualifying families than there are slots: when lighting was
    # published the grid had eight candidates for seven places, and with the
    # client's own families lower down the list it was Accessoires Solaires
    # that fell off. Priority is the order, so the named five cannot be
    # displaced by a family nobody asked for.
    'Panneaux Solaire',
    'Onduleurs Solaires',
    'Batteries Solaires',
    'Pompage Solaire',
    'Éclairage Solaire',
    'Coffrets & Protections Électriques',
    'Accessoires Solaires',
    # Fill-ins, in the order they should take a slot the seven above leave
    # empty — which is what they do while pumping has nothing published.
    'Câbles Électriques & Solaires',
    'Structures & Fixations Solaires',
)


def _key(name):
    """Compare category names the way a human reads them: case and spacing
    are noise, accents are not — "Câble" and "Cable" are two different
    catalogue entries and must not be folded together."""
    return re.sub(r'\s+', ' ', (name or '')).strip().upper()


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    tecas_show_when_empty = fields.Boolean(
        string="Afficher même sans produit publié",
        help="Garde la catégorie dans le menu et rend sa page accessible aux "
             "visiteurs tant qu'aucun produit n'y est publié. À cocher pour "
             "une famille annoncée avant d'être en ligne (les pompes), à "
             "laisser décochée partout ailleurs.",
        default=False,
    )
    tecas_hide_from_website = fields.Boolean(
        string="Masquer du site",
        help="Retire la catégorie du site — menu, page d'accueil, colonne de "
             "gauche de la boutique — sans rien changer au catalogue : la "
             "catégorie reste utilisable en interne et les produits qu'elle "
             "contient restent en ligne via leurs autres catégories.",
        default=False,
    )

    @api.model
    def _search_has_published_products(self, operator, value):
        """Decide, in one place, whether a visitor may see a category.

        `has_published_products` is the single lever the whole shop uses: the
        record rule website_sale.empty_public_categories_rule (which is why an
        empty category's page 404s), the sidebar tree, and the sub-category
        strip on a category page all read it — the strip filters on it inline,
        so nothing short of this field would reach it. Both TECAS flags are
        therefore folded in here, and only here:

          * tecas_show_when_empty announces a family before its products are
            published (the pumps);
          * tecas_hide_from_website takes a category off the site while leaving
            the catalogue untouched (Promo), and wins over everything else.

        Core's compute delegates to this method, so the field follows.
        """
        domain = super()._search_has_published_products(operator, value)
        if domain is NotImplemented:
            return domain
        return ((domain | Domain('tecas_show_when_empty', '=', True))
                & Domain('tecas_hide_from_website', '=', False))

    @api.model
    def _tecas_homepage_tiles(self, limit=7):
        """Categories for the homepage grid, in HOMEPAGE_FAMILIES order.

        Anything the list does not name fills the remaining slots by revenue,
        so a family added in the backend still reaches the homepage without a
        deploy.

        Only categories holding a published product are offered a tile. That is
        deliberately stricter than the menu, which announces an empty family on
        the tecas_show_when_empty flag: a menu entry is a promise that the page
        exists, while a homepage tile is a promise that there is something to
        buy behind it.
        """
        categories = _relevant_categories(self.env).filtered(
            lambda c: _has_published_product(self.env, c))

        by_name = {}
        for categ in categories:
            by_name.setdefault(_key(categ.name), categ)

        ordered = self.browse()
        for name in HOMEPAGE_FAMILIES:
            categ = by_name.get(_key(name))
            if categ:
                ordered |= categ

        rest = categories - ordered
        revenue = self._tecas_category_revenue(rest.ids)
        rest = rest.sorted(lambda c: revenue.get(c.id, 0.0), reverse=True)

        return (ordered + rest)[:limit]

    def _tecas_tile_image(self):
        """Image url for this category's tile, or False if it has none.

        A category rarely carries its own picture, so the catalogue supplies
        one: the first published product that has an image, then any product at
        all. The `image_512 != False` clause is what makes that work — picking
        the first published product outright, as this used to, hands back a
        blank frame whenever that product happens to have no photo.
        """
        self.ensure_one()
        if self.image_512:
            return '/web/image/product.public.category/%s/image_512' % self.id

        Product = self.env['product.template'].sudo()
        has_image = [('public_categ_ids', 'child_of', self.id),
                     ('image_512', '!=', False)]
        product = (Product.search(has_image + [('is_published', '=', True)], limit=1)
                   or Product.search(has_image, limit=1))
        return '/web/image/product.template/%s/image_512' % product.id if product else False

    @api.model
    def _tecas_category_revenue(self, category_ids):
        """{root category id: confirmed revenue}, children included.

        A product sits in a leaf category, so the totals have to roll up the
        tree: `parent_path` makes that a prefix match rather than a recursive
        walk.
        """
        if not category_ids:
            return {}
        self.env.cr.execute(
            """
            SELECT root.id, COALESCE(SUM(line.price_subtotal), 0)
              FROM product_public_category root
              JOIN product_public_category child
                ON child.parent_path LIKE root.parent_path || '%%'
              JOIN product_public_category_product_template_rel rel
                ON rel.product_public_category_id = child.id
              JOIN product_product variant
                ON variant.product_tmpl_id = rel.product_template_id
              JOIN sale_order_line line
                ON line.product_id = variant.id
              JOIN sale_order so
                ON so.id = line.order_id AND so.state IN ('sale', 'done')
             WHERE root.id IN %s
             GROUP BY root.id
            """,
            (tuple(category_ids),),
        )
        return dict(self.env.cr.fetchall())
