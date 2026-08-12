from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    shop_split_variants = fields.Boolean(
        string="Split variants in the shop",
        help="Show one tile per product variant on /shop instead of one tile per "
             "product. Variants that are out of stock stay listed but are dimmed.",
    )
