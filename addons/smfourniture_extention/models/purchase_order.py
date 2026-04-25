from odoo import models, fields, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    date_approve = fields.Datetime(
            'Confirmation Date',
            index=True,
            copy=False,
            help="The date the purchase order was confirmed.",
        )