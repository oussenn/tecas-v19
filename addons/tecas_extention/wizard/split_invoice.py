from datetime import timedelta
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from math import floor

_logger = logging.getLogger(__name__)

class SplitInvoiceWizard(models.TransientModel):
    _name = 'split.invoice.wizard'
    _description = 'Split Invoice Confirmation'

    message = fields.Text(string="Message", readonly=True)

    def action_split_invoice(self):
        """Logic to split the invoice"""
        _logger.info("Starting invoice split operation.")
        active_id = self.env.context.get('active_id')
        if not active_id:
            _logger.error("No active invoice found in context.")
            raise UserError("Aucune facture active trouvée pour la scission.")

        invoice = self.env['account.move'].browse(active_id)

        # Log initial invoice details
        _logger.info("Splitting invoice ID: %s, Total Amount: %s, Invoice Origin: %s",
                     invoice.id, invoice.amount_total, invoice.invoice_origin)

        # Ensure the invoice can be split
        if not invoice.invoice_date:
            _logger.error("Invoice date is not set. Cannot proceed with split.")
            raise UserError("Veuillez définir une date de facture avant de procéder à la scission.")
        
        if invoice.state != 'draft':
            _logger.warning("Cannot split invoice not in draft state. ID: %s", invoice.id)
            raise UserError("Vous ne pouvez scinder que les factures à l'état brouillon.")
        
        if invoice.amount_total <= 5000:
            _logger.warning("Invoice total is already <= 5000. No split needed. ID: %s", invoice.id)
            raise UserError("Le montant total est déjà inférieur ou égal à 5000. Aucune scission nécessaire.")

        # Splitting logic
        new_invoices = []
        remaining_amount = invoice.amount_total
        original_lines = invoice.invoice_line_ids

        _logger.info("Original invoice has %s lines.", len(original_lines))

        updated_original_lines = []
        split_date = fields.Date.from_string(invoice.invoice_date)  # Start with the original invoice date
        date_increment = 1  # Initial increment for the first split invoice

        for line in original_lines:
            _logger.info("Processing line ID: %s, Product: %s, Line Total: %s",
                        line.id, line.product_id.name, line.price_total)

            if remaining_amount <= 5000:
                _logger.info("Remaining amount is <= 5000. Stopping split.")
                updated_original_lines.append((1, line.id, {}))
                break

            split_amount = min(line.price_total, remaining_amount - 5000)
            remaining_amount -= split_amount

            _logger.info("Splitting line. Split Amount: %s, Remaining Amount: %s",
                        split_amount, remaining_amount)

            # Calculate the adjusted quantity for the new invoice
            adjusted_quantity = line.quantity * (split_amount / line.price_total)
            rounded_quantity = floor(adjusted_quantity)  # Ensure quantity is a whole number

            _logger.info("Adjusted and rounded quantity for split line: %s", rounded_quantity)

            # Set the date for the new invoice
            split_date += timedelta(days=date_increment)
            date_increment += 2  # Increment by 2 days for the next split invoice

            # Create a new invoice for the split line
            new_invoice_vals = {
                'partner_id': invoice.partner_id.id,
                'invoice_date': split_date,
                'state': 'draft',
                'move_type': invoice.move_type,
                'parent_invoice_id': invoice.id,
                'invoice_origin': invoice.invoice_origin,  # Ensure linkage to the sale order
                'invoice_line_ids': [(0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'quantity': rounded_quantity,  # Use the rounded quantity
                    'price_unit': line.price_unit,
                    'sale_line_ids': [(6, 0, line.sale_line_ids.ids)],
                })],
            }
            new_invoice = self.env['account.move'].create(new_invoice_vals)
            new_invoices.append(new_invoice)

            _logger.info("Created new invoice ID: %s, Origin: %s, Invoice Date: %s",
                        new_invoice.id, new_invoice.invoice_origin, split_date)

            if split_amount < line.price_total:
                remaining_quantity = line.quantity - rounded_quantity
                updated_original_lines.append((1, line.id, {'quantity': remaining_quantity}))
                _logger.info("Adjusted original line remaining quantity to: %s", remaining_quantity)
            else:
                updated_original_lines.append((2, line.id, 0))
                _logger.info("Removed fully split line ID: %s", line.id)

        # Update the original invoice lines
        invoice.write({'invoice_line_ids': updated_original_lines})
        _logger.info("Updated original invoice lines. Remaining amount: %s", remaining_amount)

        # Update the cash field if remaining amount is <= 5000
        if remaining_amount <= 5000:
            invoice.write({'cash': True})
            _logger.info("Set 'cash' field to True for invoice ID: %s", invoice.id)

        # Link the new invoices to the original invoice's sale order (if any)
        if invoice.invoice_origin:
            sale_order = self.env['sale.order'].search([('name', '=', invoice.invoice_origin)], limit=1)
            if sale_order:
                for new_invoice in new_invoices:
                    new_invoice.write({'invoice_origin': sale_order.name})
                    _logger.info("Linked split invoice ID: %s to sale order ID: %s", new_invoice.id, sale_order.id)

        # Log the new invoices on the original invoice's chatter
        invoice.message_post(
            body="Cette facture a été scindée en les factures suivantes : %s" % ", ".join(
                [f'<a href="#" data-oe-model="account.move" data-oe-id="{inv.id}">{inv.name}</a>' for inv in new_invoices]
            )
        )
        _logger.info("Posted message on original invoice with references to new invoices.")

        return {
            'type': 'ir.actions.act_window_close',
        }

    def action_cancel(self):
        """Cancel the operation"""
        return {'type': 'ir.actions.act_window_close'}
