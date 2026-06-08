import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.message_type == 'inbound':
                try:
                    self.env['whatsapp.ai.bot'].handle_incoming_message(record.id)
                except Exception:
                    _logger.exception(
                        'WhatsappAIBot: hook error on whatsapp.message %s', record.id
                    )
        return records
