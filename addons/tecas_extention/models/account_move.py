import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import formatLang

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    cash = fields.Boolean(string="Cash", default=False)
    parent_invoice_id = fields.Many2one('account.move', string="Parent Invoice")
    child_invoice_ids = fields.One2many('account.move', 'parent_invoice_id', string="Split Invoices")
    split_invoice_count = fields.Integer(
        string="Split Invoice Count",
        compute="_compute_split_invoice_count",
        help="The number of split invoices related to this invoice."
    )
    stamp_duty = fields.Float(
        string="Frais de Timbre",
        compute="_compute_stamp_duty",
        store=True,
    )
    net_to_pay = fields.Float(
        string="Net à Payer",
        compute="_compute_net_to_pay",
        store=True,
    )

    def _compute_tax_totals(self):
        super()._compute_tax_totals()
        for move in self:
            if move.is_invoice(include_receipts=True) and move.cash and move.tax_totals:
                stamp_duty = move.amount_total * 0.0025
                net_to_pay = move.amount_total + stamp_duty
                tax_totals = dict(move.tax_totals)
                tax_totals['stamp_duty'] = {
                    'name': "Frais de Timbre",
                    'formatted_amount': formatLang(self.env, stamp_duty, currency_obj=move.currency_id),
                }
                tax_totals['net_to_pay'] = {
                    'name': "Net à Payer",
                    'formatted_amount': formatLang(self.env, net_to_pay, currency_obj=move.currency_id),
                }
                move._cache['tax_totals'] = tax_totals

    @api.depends('amount_total', 'move_type')
    def _compute_stamp_duty(self):
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund'):
                move.stamp_duty = move.amount_total * 0.0025
            else:
                move.stamp_duty = 0.0

    @api.depends('amount_total', 'stamp_duty')
    def _compute_net_to_pay(self):
        for move in self:
            move.net_to_pay = move.amount_total + move.stamp_duty

    @api.depends('child_invoice_ids')
    def _compute_split_invoice_count(self):
        for record in self:
            record.split_invoice_count = len(record.child_invoice_ids)

    def action_view_split_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Split Invoices',
            'view_mode': 'list,form',
            'res_model': 'account.move',
            'domain': [('parent_invoice_id', '=', self.id)],
            'context': dict(self.env.context),
        }

    def action_open_split_wizard(self):
        self.ensure_one()
        return {
            'name': 'Split Invoice Confirmation',
            'type': 'ir.actions.act_window',
            'res_model': 'split.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'views': [(self.env.ref('tecas_extention.view_split_invoice_wizard_form').id, 'form')],
            'context': {
                'default_message': f"Le montant total ({self.amount_total}). Voulez-vous scinder cette facture ?",
                'active_id': self.id,
            },
        }
