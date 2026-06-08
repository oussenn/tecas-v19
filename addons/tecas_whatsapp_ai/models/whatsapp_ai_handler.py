import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

from markupsafe import Markup
from odoo import api, models

_logger = logging.getLogger(__name__)

_AI_API_URL = 'https://api.openai.com/v1/chat/completions'

_PRODUCT_KEYWORDS = {'panneau', 'batterie', 'onduleur', 'materiel', 'matériel',
                     'stock', 'disponible', 'référence', 'reference'}
_PROMO_KEYWORDS   = {'promo', 'promotion', 'offre', 'remise', 'réduction', 'reduction'}
_HOURS_KEYWORDS   = {'conseiller', 'disponible', 'rappel', 'horaire', 'quand', 'urgent'}

_SERVICE_LABELS = {
    'residential':         'Projet résidentiel',
    'pumping':             'Pompage solaire',
    'industrial':          'Projet industriel/commercial',
    'equipment_panels':    'Achat matériel — Panneaux solaires',
    'equipment_batteries': 'Achat matériel — Batteries lithium',
    'equipment_inverters': 'Achat matériel — Onduleurs',
    'equipment_cables':    'Achat matériel — Câbles et accessoires',
    'sav':                 'SAV',
    'quick_quote':         'Devis rapide',
    'showroom':            'Visite showroom',
    'advisor':             'Parler à un conseiller',
}

# Morocco is UTC+1 year-round (no DST)
_TZ_MOROCCO = timezone(timedelta(hours=1))


class TecasWhatsappAI(models.AbstractModel):
    _name = 'tecas.whatsapp.ai'
    _description = 'TECAS WhatsApp AI Handler'

    @api.model
    def handle_incoming_message(self, whatsapp_msg_id):
        """Process an inbound whatsapp.message and respond via OpenAI."""
        config = self.env['tecas.whatsapp.ai.config'].sudo().get_singleton()
        if not config.active:
            return

        try:
            msg = self.env['whatsapp.message'].browse(whatsapp_msg_id)
            if not msg.exists():
                _logger.warning('TecasWhatsappAI: msg %s does not exist', whatsapp_msg_id)
                return

            if not self._is_service_commercial(msg, config):
                return

            channel = self._get_channel(msg)
            if not channel:
                return

            if self._human_has_taken_over(channel, config):
                _logger.info(
                    'TecasWhatsappAI: channel %s — human agent active, AI skipped',
                    channel.id,
                )
                return

            if not config.openai_api_key:
                _logger.error(
                    'TecasWhatsappAI: OpenAI API key not set -- configure it in WhatsApp > Bot'
                )
                return

            messages = self._build_messages(channel)
            if not messages:
                _logger.warning(
                    'TecasWhatsappAI: msg %s -- no conversation history for channel %s',
                    whatsapp_msg_id, channel.id,
                )
                return

            context_block = self._build_context_block(channel, messages)
            result = self._call_openai(messages, config, context_block)
            if result is None:
                return

            reply = (result.get('reponse') or '').strip()
            service = (result.get('service') or 'unknown').strip()
            if not result.get('escalade', False):
                if reply:
                    self._post_whatsapp_reply(channel, reply)
            else:
                raison = result.get('raison') or 'Escalade demandee par le client.'
                partner = self._channel_partner(channel)
                existing_lead = self._find_existing_lead(partner)
                if existing_lead and existing_lead.user_id:
                    salesman = existing_lead.user_id
                    _logger.info(
                        'TecasWhatsappAI: reusing lead=%s salesman=%s for partner=%s',
                        existing_lead.id, salesman.id, partner.id if partner else None,
                    )
                else:
                    salesman = self._get_next_salesman(config)
                    _logger.info(
                        'TecasWhatsappAI: no existing lead/salesman, round-robin -> salesman=%s',
                        salesman.id if salesman else None,
                    )
                if salesman:
                    self._escalate(channel, msg, raison, salesman, messages, service)
                else:
                    _logger.warning(
                        'TecasWhatsappAI: No salesmen configured -- add users in WhatsApp > Bot'
                    )
                if reply:
                    self._post_whatsapp_reply(channel, reply)

        except Exception:
            _logger.exception(
                'TecasWhatsappAI: Unexpected error processing message %s',
                whatsapp_msg_id,
            )

    # ------------------------------------------------------------------
    # Account / channel helpers
    # ------------------------------------------------------------------

    def _is_service_commercial(self, msg, config):
        """Return True only when the message belongs to the configured WhatsApp account."""
        if not config.wa_account_id:
            _logger.warning(
                'TecasWhatsappAI: No WhatsApp account selected in Bot configuration'
            )
            return False
        return msg.wa_account_id.id == config.wa_account_id.id

    def _get_channel(self, msg):
        """Return the discuss.channel linked to this whatsapp.message."""
        mail_msg = msg.mail_message_id
        if not mail_msg or mail_msg.model != 'discuss.channel':
            _logger.warning(
                'TecasWhatsappAI: No discuss.channel linked to whatsapp.message %s',
                msg.id,
            )
            return False
        channel = self.env['discuss.channel'].browse(mail_msg.res_id)
        if not channel.exists():
            _logger.warning(
                'TecasWhatsappAI: discuss.channel %s not found for whatsapp.message %s',
                mail_msg.res_id, msg.id,
            )
            return False
        return channel

    def _human_has_taken_over(self, channel, config):
        """
        Return True if a human replied in this channel within the takeover window.
        - 0   : disabled — AI always responds
        - N>0 : AI stays silent for N days after the last human reply, then resumes
        """
        days = config.human_takeover_days
        if days == 0:
            return False

        bot_partner_id = self.env.ref('base.partner_root').id
        customer_partner = self._channel_partner(channel)
        excluded_ids = [bot_partner_id]
        if customer_partner:
            excluded_ids.append(customer_partner.id)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        domain = [
            ('res_id', '=', channel.id),
            ('model', '=', 'discuss.channel'),
            ('message_type', '=', 'whatsapp_message'),
            ('author_id', 'not in', excluded_ids),
            ('author_id', '!=', False),
            ('date', '>=', cutoff.replace(tzinfo=None)),
        ]

        return bool(self.env['mail.message'].sudo().search(domain, limit=1))

    # ------------------------------------------------------------------
    # Conversation building
    # ------------------------------------------------------------------

    def _build_messages(self, channel):
        """Return the last 20 messages as an OpenAI-compatible list of dicts."""
        wa_msgs = self.env['whatsapp.message'].search(
            [
                ('mail_message_id.model', '=', 'discuss.channel'),
                ('mail_message_id.res_id', '=', channel.id),
            ],
            order='id desc',
            limit=10,
        )
        wa_msgs = wa_msgs.sorted('id')

        result = []
        for wa_msg in wa_msgs:
            body = self._strip_html(wa_msg.mail_message_id.body or '')
            if not body:
                continue
            role = 'user' if wa_msg.message_type == 'inbound' else 'assistant'
            # Merge consecutive same-role turns (OpenAI requires alternating roles)
            if result and result[-1]['role'] == role:
                result[-1]['content'] += '\n' + body
            else:
                result.append({'role': role, 'content': body})

        while result and result[0]['role'] != 'user':
            result.pop(0)

        return result

    @staticmethod
    def _strip_html(text):
        """Remove HTML tags and decode common entities."""
        text = re.sub(r'<[^>]+>', '', text or '')
        text = (
            text
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&nbsp;', ' ')
        )
        return text.strip()

    # ------------------------------------------------------------------
    # Lazy context injection
    # ------------------------------------------------------------------

    def _build_context_block(self, channel, messages):
        """
        Analyze the last 3 messages for intent keywords and return a context
        string to append to the system prompt. Returns '' if nothing applies.
        Token budget: ~400 tokens (≈1600 chars). Products truncated first,
        then promos. CRM lead and business hours are always kept when triggered.
        """
        recent = ' '.join(m['content'] for m in messages[-3:]).lower()
        # Normalize accented chars for keyword matching
        recent_norm = (
            recent
            .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
            .replace('à', 'a').replace('â', 'a')
            .replace('ô', 'o').replace('û', 'u').replace('î', 'i')
            .replace('ç', 'c')
        )

        blocks_optional = []   # (key, text) — truncated if over budget
        blocks_priority = []   # (key, text) — always kept

        # 1. Product catalog
        if _PRODUCT_KEYWORDS & set(recent_norm.split()):
            try:
                products = self.env['product.template'].sudo().search(
                    [('sale_ok', '=', True), ('active', '=', True)],
                    order='categ_id asc',
                    limit=20,
                )
                if products:
                    lines = ['CATALOGUE PRODUITS (stock actuel, sans prix) :']
                    for p in products:
                        try:
                            qty = int(p.qty_available)
                        except Exception:
                            qty = 0
                        categ = p.categ_id.name if p.categ_id else '—'
                        lines.append('- [%s] %s : %d unités' % (categ, p.name, qty))
                    blocks_optional.append(('products', '\n'.join(lines)))
            except Exception:
                _logger.warning('TecasWhatsappAI: context — product catalog query failed')

        # 2. Active promotions
        if _PROMO_KEYWORDS & set(recent_norm.split()):
            try:
                promos = self.env['product.template'].sudo().search(
                    [
                        ('sale_ok', '=', True),
                        ('active', '=', True),
                        ('description_sale', 'ilike', 'promo'),
                    ],
                    limit=5,
                )
                if promos:
                    lines = ['PROMOTIONS EN COURS :']
                    for p in promos:
                        desc = (p.description_sale or '').strip().replace('\n', ' ')[:120]
                        lines.append('- %s : %s' % (p.name, desc))
                    blocks_optional.append(('promos', '\n'.join(lines)))
            except Exception:
                _logger.warning('TecasWhatsappAI: context — promotions query failed')

        # 3. Existing CRM lead — always checked
        try:
            partner = self._channel_partner(channel)
            if partner:
                lead = self._find_existing_lead(partner)
                if lead:
                    stage = lead.stage_id.name if lead.stage_id else 'N/A'
                    salesman = lead.user_id.name if lead.user_id else 'Non assigné'
                    last_act = (
                        lead.activity_date_deadline.strftime('%d/%m/%Y')
                        if lead.activity_date_deadline else 'N/A'
                    )
                    lines = [
                        'LEAD CRM EXISTANT (ne pas redemander ces infos) :',
                        '- Nom : %s' % lead.name,
                        '- Étape : %s' % stage,
                        '- Commercial : %s' % salesman,
                        '- Dernière activité : %s' % last_act,
                    ]
                    blocks_priority.append(('lead', '\n'.join(lines)))
        except Exception:
            _logger.warning('TecasWhatsappAI: context — CRM lead query failed')

        # 4. Business hours
        if _HOURS_KEYWORDS & set(recent_norm.split()):
            try:
                now = datetime.now(_TZ_MOROCCO)
                weekday = now.weekday()  # 0=Mon … 6=Sun
                frac_hour = now.hour + now.minute / 60.0
                if weekday < 5:
                    open_now = 8.5 <= frac_hour < 18.0
                elif weekday == 5:
                    open_now = 8.5 <= frac_hour < 13.0
                else:
                    open_now = False
                status = 'OUVERT — un conseiller est disponible' if open_now else 'FERMÉ en ce moment'
                lines = [
                    'HORAIRES D\'OUVERTURE (%s) :' % status,
                    '- Lun–Ven : 08:30–18:00',
                    '- Sam : 08:30–13:00',
                    '- Dim : fermé',
                ]
                blocks_priority.append(('hours', '\n'.join(lines)))
            except Exception:
                _logger.warning('TecasWhatsappAI: context — business hours computation failed')

        if not blocks_optional and not blocks_priority:
            return ''

        # Apply token budget (~400 tokens ≈ 1600 chars)
        CHAR_BUDGET = 1600
        parts = []

        # Priority blocks first (always kept)
        for _k, text in blocks_priority:
            parts.append(text)

        chars_used = sum(len(p) for p in parts)

        # Optional blocks — truncate products first, then promos
        for key, text in blocks_optional:
            remaining = CHAR_BUDGET - chars_used
            if remaining <= 0:
                break
            if len(text) <= remaining:
                parts.append(text)
                chars_used += len(text)
            elif key == 'products':
                # Partial product list
                lines = text.split('\n')
                kept = [lines[0]]  # header
                for line in lines[1:]:
                    if chars_used + len('\n'.join(kept)) + len(line) + 1 <= CHAR_BUDGET:
                        kept.append(line)
                    else:
                        kept.append('(liste tronquée pour économiser des tokens)')
                        break
                truncated = '\n'.join(kept)
                parts.append(truncated)
                chars_used += len(truncated)
            # promos: skip entirely if no room

        if not parts:
            return ''

        return '\n\n---\nCONTEXTE TEMPS RÉEL :\n' + '\n\n'.join(parts)

    # ------------------------------------------------------------------
    # OpenAI API
    # ------------------------------------------------------------------

    def _call_openai(self, messages, config, context_block=''):
        """Send messages to OpenAI and return the parsed JSON dict, or None on error."""
        system_prompt = config.system_prompt
        if context_block:
            system_prompt = system_prompt + context_block

        payload = json.dumps({
            'model': config.ai_model,
            'max_tokens': config.max_tokens,
            'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
        }).encode('utf-8')

        req = urllib.request.Request(
            _AI_API_URL,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer %s' % config.openai_api_key,
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_text = data['choices'][0]['message']['content'].strip()
                return self._parse_json_response(raw_text)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            _logger.error('TecasWhatsappAI: OpenAI HTTP %s -- %s', exc.code, body[:500])
        except urllib.error.URLError as exc:
            _logger.error('TecasWhatsappAI: OpenAI network error -- %s', exc.reason)
        return None

    @staticmethod
    def _parse_json_response(text):
        """Extract the JSON object from the AI reply, tolerating markdown fences."""
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        block = re.search(r'\{[^{}]*"escalade"[^{}]*\}', text, re.DOTALL)
        if block:
            text = block.group(0)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            _logger.error(
                'TecasWhatsappAI: Cannot parse AI response as JSON: %s',
                text[:400],
            )
            return None

    # ------------------------------------------------------------------
    # Reply posting
    # ------------------------------------------------------------------

    def _post_whatsapp_reply(self, channel, reply):
        """Post the AI-generated reply to the WhatsApp discuss channel."""
        try:
            channel.sudo().message_post(
                body=reply,
                message_type='whatsapp_message',
                subtype_xmlid='mail.mt_comment',
                author_id=self.env.ref('base.partner_root').id,
            )
        except Exception:
            _logger.exception('TecasWhatsappAI: Failed to post WhatsApp reply.')

    # ------------------------------------------------------------------
    # Round-robin salesman selection
    # ------------------------------------------------------------------

    def _get_next_salesman(self, config):
        """Return the next active res.users from the configured pool (round-robin)."""
        users = config.salesman_ids.filtered('active')
        if not users:
            return False

        count = len(users)
        start = (config.last_salesman_index + 1) % count
        for offset in range(count):
            candidate = users[(start + offset) % count]
            if candidate.active:
                config.sudo().write({'last_salesman_index': (start + offset) % count})
                return candidate
        return False

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(self, channel, msg, raison, salesman, messages, service='unknown'):
        """Assign or create a CRM lead and send a briefing to the salesman."""
        partner = self._channel_partner(channel)
        lead = self._get_or_create_lead(partner, msg, salesman, service)
        if lead:
            effective_salesman = lead.user_id or salesman
            if partner and effective_salesman:
                partner.sudo().write({'user_id': effective_salesman.id})
            self._post_lead_briefing(lead, effective_salesman, partner, msg, raison, messages)
        else:
            self._notify_salesman_inbox(salesman, msg, raison, messages)

    def _channel_partner(self, channel):
        """Return the customer partner for this WhatsApp channel."""
        partner = getattr(channel, 'whatsapp_partner_id', False)
        if not partner:
            bot_id = self.env.ref('base.partner_root').id
            members = channel.channel_member_ids.filtered(
                lambda m: m.partner_id and m.partner_id.id != bot_id
            )
            partner = members[:1].partner_id or False
        return partner

    def _find_existing_lead(self, partner):
        """Return the most recent active CRM lead for this partner, or False.

        Searches by partner first, then falls back to phone to handle cases
        where the same customer has multiple partner records.
        """
        if not partner:
            return False

        lead = self.env['crm.lead'].sudo().search(
            [('partner_id', '=', partner.id), ('active', '=', True)],
            order='create_date desc',
            limit=1,
        )
        if not lead:
            phone = partner.phone or getattr(partner, 'mobile', None)
            if phone:
                lead = self.env['crm.lead'].sudo().search(
                    [('phone', '=', phone), ('active', '=', True)],
                    order='create_date desc',
                    limit=1,
                )

        _logger.info(
            'TecasWhatsappAI: _find_existing_lead partner=%s phone=%s -> lead=%s user_id=%s',
            partner.id, partner.phone, lead.id if lead else None,
            lead.user_id.id if lead and lead.user_id else None,
        )
        return lead or False

    def _get_or_create_lead(self, partner, msg, salesman, service='unknown'):
        """Return the most recent open lead for the contact, or create a new one.

        When a lead already exists, keep the original salesman and update the
        lead name to reflect the new service. Never overwrite user_id.
        """
        if not partner:
            return False

        service_label = _SERVICE_LABELS.get(service, '')
        contact_name = partner.name or msg.mobile_number or 'Inconnu'
        lead_name = (
            'WhatsApp — %s — %s' % (service_label, contact_name)
            if service_label else
            'WhatsApp — Prospect — %s' % contact_name
        )

        lead = self._find_existing_lead(partner)
        if lead:
            vals = {'name': lead_name}
            if not lead.user_id and salesman:
                vals['user_id'] = salesman.id
            lead.sudo().write(vals)
        else:
            lead = self.env['crm.lead'].sudo().create({
                'name': lead_name,
                'partner_id': partner.id,
                'user_id': salesman.id,
                'phone': partner.phone or msg.mobile_number or '',
                'description': (
                    'Lead genere automatiquement depuis WhatsApp par l\'assistant AI TECAS.'
                ),
            })
        return lead

    def _build_conversation_html(self, messages):
        """Render the last 10 conversation turns as an HTML snippet."""
        lines = []
        for m in messages[-10:]:
            label = 'Client' if m['role'] == 'user' else 'TECAS AI'
            content = m['content'].replace('\n', '<br/>')
            lines.append('<b>%s :</b> %s' % (label, content))
        return '<br/><br/>'.join(lines) if lines else '(aucun historique)'

    def _post_lead_briefing(self, lead, salesman, partner, msg, raison, messages):
        """Post a briefing note on the CRM lead and notify the salesman."""
        phone = (partner.phone or partner.mobile or msg.mobile_number or 'N/A') if partner else (msg.mobile_number or 'N/A')
        convo_html = self._build_conversation_html(messages)
        body = (
            '<p><b>Escalade WhatsApp AI -- Action requise</b></p>'
            '<table style="border-collapse:collapse;margin-bottom:8px">'
            '<tr><td style="padding:2px 8px 2px 0"><b>Contact</b></td>'
            '<td>%s</td></tr>'
            '<tr><td style="padding:2px 8px 2px 0"><b>Telephone</b></td>'
            '<td>%s</td></tr>'
            '<tr><td style="padding:2px 8px 2px 0"><b>Raison de l\'escalade</b></td>'
            '<td>%s</td></tr>'
            '</table>'
            '<p><b>Historique de la conversation :</b></p>'
            '<div style="background:#f5f5f5;padding:10px 14px;border-left:4px solid #00a09d;'
            'font-size:13px;line-height:1.6">%s</div>'
            '<p style="margin-top:10px">Veuillez contacter ce prospect dans les plus brefs '
            'delais via WhatsApp ou par telephone.</p>'
        ) % (
            partner.name if partner else 'Inconnu',
            phone,
            raison,
            convo_html,
        )
        lead.sudo().message_post(
            body=Markup(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=[salesman.partner_id.id],
        )

    def _notify_salesman_inbox(self, salesman, msg, raison, messages):
        """Fallback notification when no CRM lead could be created."""
        convo_html = self._build_conversation_html(messages)
        body = (
            '<p><b>Escalade WhatsApp AI -- Aucun lead CRM disponible</b></p>'
            '<p><b>Telephone client :</b> %s</p>'
            '<p><b>Raison de l\'escalade :</b> %s</p>'
            '<p><b>Historique de la conversation :</b></p>'
            '<div style="background:#f5f5f5;padding:10px 14px;border-left:4px solid #00a09d;'
            'font-size:13px;line-height:1.6">%s</div>'
        ) % (msg.mobile_number or 'N/A', raison, convo_html)
        salesman.sudo().partner_id.message_post(
            body=Markup(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
