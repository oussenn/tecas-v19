from datetime import datetime
from odoo import models, fields, _
import logging

_logger = logging.getLogger(__name__)

from datetime import datetime
from odoo import models, fields, _
import logging

_logger = logging.getLogger(__name__)

class SaleOrderToInvoiceReport(models.AbstractModel):
    _name = 'report.smfourniture_extention.report_sale_order_to_invoice'
    _description = 'Sales Orders to Invoice Report'


    def _get_report_values(self, docids, data=None):
        # Fetch the sale orders directly using the docids
        sale_orders = self.env['sale.order'].browse(docids)

        # Validate that the sale orders belong to a single client
        partner_ids = sale_orders.mapped('partner_id')
        if len(partner_ids) != 1:
            _logger.warning("The report can only be generated for a single client. Found multiple or no clients.")
            return {}

        client = partner_ids[0]  # Get the unique partner (client)

        # Prepare data for return adjustments
        order_lines_data = []
        for order in sale_orders:
            _logger.info(f"Processing Sale Order: {order.name}")
            _logger.info(f"Pickings for Sale Order {order.name}: {[(p.name, p.picking_type_id.code, p.state) for p in order.picking_ids]}")

            for line in order.order_line:
                # Add the original sale order line
                order_lines_data.append({
                    'order': order,
                    'line': line,
                    'quantity': line.product_uom_qty,
                    'price': line.price_unit,
                    'subtotal': line.price_subtotal,
                    'description': line.product_id.display_name,
                    'return_quantity': 0,  # Default value for lines without returns
                    'is_return': False,  # Flag to indicate this is not a return
                    'date': order.date_order,  # Use the sale order date for the original line
                })

                # Check for return pickings
                return_pickings = order.picking_ids.filtered(
                    lambda p: p.picking_type_id.code == 'incoming' and p.state == 'done'
                )
                for return_picking in return_pickings:  # Iterate through each return picking
                    for move in return_picking.move_ids:
                        if move.product_id == line.product_id:
                            # Add the return line
                            order_lines_data.append({
                                'order': order,
                                'line': line,
                                'quantity': -move.product_uom_qty,
                                'price': line.price_unit,
                                'subtotal': -move.product_uom_qty * line.price_unit,
                                'description': f"Return ({return_picking.name}) - {line.product_id.display_name}",
                                'return_quantity': move.product_uom_qty,  # Actual return quantity
                                'is_return': True,  # Flag to indicate this is a return
                                'date': return_picking.scheduled_date,  # Use the return picking date for the return line
                            })
                            _logger.info(
                                f"Return line added: Sale Order {order.name}, Product {line.product_id.name}, "
                                f"Return Quantity: {move.product_uom_qty}, Return Picking: {return_picking.name}, Date: {return_picking.scheduled_date}"
                            )






        # Generate current date
        current_date = datetime.now().strftime('%d/%m/%Y')

        # Log summary of all data
        _logger.info(f"Generating report for client: {client.name}")
        _logger.info(f"Number of selected sale orders: {len(sale_orders)}")
        _logger.info(f"Prepared data for report: {order_lines_data}")

        # Pass the data to the template
        return {
            'docs': sale_orders,
            'order_lines_data': order_lines_data,
            'client': client,
            'print_date': current_date,
        }

