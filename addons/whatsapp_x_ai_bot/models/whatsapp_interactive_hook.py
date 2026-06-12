import logging
from odoo import models

_logger = logging.getLogger(__name__)


class WhatsappAccountInteractiveHook(models.Model):
    _inherit = 'whatsapp.account'

    def _process_messages(self, value):
        """Extend to handle interactive quick-reply button replies from the bot's restart button."""
        if 'messages' not in value:
            value = value.get('whatsapp_business_api_data', value)
        for msg in value.get('messages', []):
            if msg.get('type') == 'interactive':
                interactive = msg.get('interactive', {})
                itype = interactive.get('type')
                if itype == 'button_reply':
                    btn_id = interactive['button_reply'].get('id', '0')
                    msg['type'] = 'button'
                    msg['button'] = {'text': btn_id}
                    _logger.info('WhatsappAIBot: button_reply -> id=%s', btn_id)
                elif itype == 'list_reply':
                    row_id = interactive['list_reply'].get('id', '0')
                    msg['type'] = 'button'
                    msg['button'] = {'text': row_id}
                    _logger.info('WhatsappAIBot: list_reply -> id=%s', row_id)
        return super()._process_messages(value)
