from odoo import api, models

from .tecas_autosync import _relevant_categories

# The families that always lead the homepage grid, whatever the sales say.
# Matched on name rather than id so the pinning survives a category being
# recreated, and so it reads as a rule instead of a magic number.
PINNED_PREFIXES = ('PANNEAU', 'ONDULEUR')


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    @api.model
    def _tecas_homepage_tiles(self, limit=7):
        """Categories for the homepage grid.

        Panels and inverters lead because they are what TECAS sells; the rest
        of the row is filled by revenue, so the grid follows the catalogue
        instead of being hand-maintained.

        Only categories holding a published product are considered at all —
        `/shop/category/<id>` 404s otherwise, so an unpublished category would
        put a dead link on the homepage.
        """
        categories = _relevant_categories(self.env)

        pinned = self.browse()
        for prefix in PINNED_PREFIXES:
            pinned |= categories.filtered(
                lambda c, p=prefix: (c.name or '').upper().startswith(p)
            )

        rest = categories - pinned
        revenue = self._tecas_category_revenue(rest.ids)
        rest = rest.sorted(lambda c: revenue.get(c.id, 0.0), reverse=True)

        return (pinned + rest)[:limit]

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
