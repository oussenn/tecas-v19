from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    shop_split_variants = fields.Boolean(
        related='website_id.shop_split_variants',
        readonly=False,
    )
