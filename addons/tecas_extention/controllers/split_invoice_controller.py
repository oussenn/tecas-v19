from odoo import http
from odoo.http import request

class SplitInvoiceController(http.Controller):

    @http.route('/split_invoice_wizard', type='json', auth='user')
    def open_split_wizard(self, record_id):
        """Open the Split Invoice Wizard for the given record ID."""
        invoice = request.env['account.move'].browse(record_id)
        if invoice:
            return {
                'name': 'Split Invoice Confirmation',
                'type': 'ir.actions.act_window',
                'res_model': 'split.invoice.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_message': (
                        f"The total amount ({invoice.amount_total}) exceeds 5000. "
                        "Do you want to split this invoice?"
                    ),
                    'active_id': invoice.id,
                },
            }
        return {}
