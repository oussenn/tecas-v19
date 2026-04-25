from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_coa_installed = fields.Boolean(string="COA Installed", default=False)

    
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_view_invoice(self):
        # Call the original function to get the base action
        action = super(SaleOrder, self).action_view_invoice()

        # Add split invoices to the domain
        invoices = self.env['account.move'].search([('parent_invoice_id', 'in', self.invoice_ids.ids)])
        invoice_ids = invoices.ids

        # Ensure the domain is a list
        if isinstance(action.get('domain'), list):
            # Append split invoices to the existing domain
            action['domain'] = ['|'] + action['domain'] + [('id', 'in', invoice_ids)]
        else:
            # If the domain is not a list, set it as a new one
            action['domain'] = [('id', 'in', self.invoice_ids.ids + invoice_ids)]

        return action

    def action_view_invoice(self):
        # Call the original method to get the default behavior
        action = super(SaleOrder, self).action_view_invoice()

        # Include split invoices linked to the sale order
        split_invoices = self.env['account.move'].search([
            ('parent_invoice_id', 'in', self.invoice_ids.ids)  # Fetch invoices with parent_invoice_id linked to current invoices
        ])

        # Combine the original invoices and split invoices
        all_invoices = self.invoice_ids | split_invoices

        # Modify the domain to include all invoices
        if len(all_invoices) > 1:
            action['domain'] = [('id', 'in', all_invoices.ids)]
        elif len(all_invoices) == 1:
            action['res_id'] = all_invoices.id

        return action
