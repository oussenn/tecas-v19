from datetime import datetime
from odoo import models, fields, _
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrderToInvoiceReport(models.AbstractModel):
    _name = 'report.smfourniture_extention.report_purchase_order_to_invoice'
    _description = 'Vendor Purchase Orders to Invoice Report'

    def _get_report_values(self, docids, data=None):
        _logger.info("✅ Calling `_get_report_values` function for Purchase Order to Invoice Report.")
        purchase_orders = self.env['purchase.order'].browse(docids)

        # Validate that the purchase orders belong to a single vendor
        vendor_ids = purchase_orders.mapped('partner_id')
        if not vendor_ids:
            _logger.error("No vendor found for the selected purchase orders.")
            return {}

        if len(vendor_ids) > 1:
            _logger.warning("The report can only be generated for a single vendor. Found multiple vendors.")
            return {}

        vendor = vendor_ids[0]  # Get the unique vendor (partner)

        # Prepare data for vendor returns
        purchase_lines_data = []
        for order in purchase_orders:
            _logger.info(f"Processing Purchase Order: {order.name}")

            for line in order.order_line:
                # Compute tax dynamically based on applied taxes
                tax_amount = sum((line.product_qty * line.price_unit) * (tax.amount / 100) for tax in line.tax_ids)

                # Add the original purchase order line
                purchase_lines_data.append({
                    'order': order,
                    'line': line,
                    'quantity': line.product_qty,
                    'price': line.price_unit,
                    'subtotal': line.price_subtotal,
                    'tax_amount': tax_amount,  # Store the computed tax
                    'description': line.product_id.display_name,
                    'return_quantity': 0,  # Default value for lines without returns
                    'is_return': False,  # Flag to indicate this is not a return
                    'date': order.date_order,  # Use the purchase order date for the original line
                })

                # Check for return pickings (Vendor Returns)
                return_pickings = order.picking_ids.filtered(
                    lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'done'
                )
                for return_picking in return_pickings:
                    for move in return_picking.move_ids:
                        if move.product_id == line.product_id:
                            return_tax_amount = sum((-move.product_uom_qty * line.price_unit) * (tax.amount / 100) for tax in line.tax_ids)

                            # Add the return line
                            purchase_lines_data.append({
                                'order': order,
                                'line': line,
                                'quantity': -move.product_uom_qty,
                                'price': line.price_unit,
                                'subtotal': -move.product_uom_qty * line.price_unit,
                                'tax_amount': return_tax_amount,  # Tax for return should be negative
                                'description': f"Return ({return_picking.name}) - {line.product_id.display_name}",
                                'return_quantity': move.product_uom_qty,
                                'is_return': True,
                                'date': return_picking.scheduled_date,
                            })
                            _logger.info(
                                f"Return line added: Purchase Order {order.name}, Product {line.product_id.name}, "
                                f"Return Quantity: {move.product_uom_qty}, Return Picking: {return_picking.name}, Date: {return_picking.scheduled_date}"
                            )

        # Generate current date
        current_date = datetime.now().strftime('%d/%m/%Y')

        # Log summary of all data
        _logger.info(f"Generating report for vendor: {vendor.name}")
        _logger.info(f"Number of selected purchase orders: {len(purchase_orders)}")

        return {
            'docs': purchase_orders,
            'purchase_lines_data': purchase_lines_data,
            'vendor': vendor,  # ✅ Ensure vendor is included
            'print_date': current_date,
        }
