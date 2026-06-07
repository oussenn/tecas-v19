from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'
    is_coa_installed = fields.Boolean(string="COA Installed", default=False)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_view_invoice(self, invoices=False):
        # Call original with invoices kwarg (v19 signature)
        action = super(SaleOrder, self).action_view_invoice(invoices=invoices)
        # Include split invoices linked to this sale order
        split_invoices = self.env['account.move'].search([
            ('parent_invoice_id', 'in', self.invoice_ids.ids)
        ])
        all_invoices = self.invoice_ids | split_invoices
        if len(all_invoices) > 1:
            action['domain'] = [('id', 'in', all_invoices.ids)]
        elif len(all_invoices) == 1:
            action['res_id'] = all_invoices.id
        return action
