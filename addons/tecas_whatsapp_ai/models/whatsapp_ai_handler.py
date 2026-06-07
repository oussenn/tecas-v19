import json
import logging
import re
import urllib.error
import urllib.request

from odoo import api, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt - instructs Claude to act as TECAS commercial assistant
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "Tu es l'assistant commercial de TECAS ENERGIE SOLAIRE, une entreprise marocaine "
    "specialisee dans l'installation de systemes photovoltaiques.\n\n"
    "PRODUITS ET SERVICES TECAS :\n"
    "- Panneaux solaires photovoltaiques (residentiels, industriels, agricoles)\n"
    "- Onduleurs hybrides, on-grid et off-grid\n"
    "- Batteries de stockage lithium et AGM\n"
    "- Installation cle en main avec suivi et maintenance\n"
    "- Interventions dans tout le Maroc (Casablanca, Rabat, Marrakech, Fes, Agadir, Tanger...)\n\n"
    "TON ROLE :\n"
    "Qualifier les prospects entrants et collecter les trois informations indispensables "
    "pour qu'un technicien puisse preparer un devis.\n\n"
    "INFORMATIONS OBLIGATOIRES A COLLECTER (une a la fois) :\n"
    "1. Surface disponible sur le toit en m2 (ou nombre de panneaux envisage)\n"
    "2. Consommation mensuelle d'electricite en kWh ou montant de la facture ONEE en DH\n"
    "3. Ville / region d'installation\n\n"
    "REGLES ABSOLUES :\n"
    "- Tu ne donnes JAMAIS de prix fermes ni de devis chiffres -- renvoie toujours "
    "vers une evaluation sur site\n"
    "- Pose UNE seule question a la fois, de maniere naturelle et chaleureuse\n"
    "- Reponds dans la langue du client (francais ou darija marocain)\n"
    "- Sois concis, professionnel et enthousiaste\n"
    "- N'invente pas d'informations techniques specifiques (rendements exacts, marques...)\n\n"
    "QUAND ESCALADER (passer la main a un commercial humain) :\n"
    "- Le client demande un devis, un prix ou une estimation chiffree\n"
    "- Le client veut parler a un commercial, un technicien ou un responsable\n"
    "- Le client exprime une intention d'achat claire (\"je veux acheter\", \"je suis decide\")\n"
    "- La conversation devient tres technique (dimensionnement precis, protections, schemas)\n"
    "- Les trois informations requises ont deja ete collectees\n"
    "- Le client semble frustre ou impatient\n\n"
    "FORMAT DE REPONSE -- JSON STRICT UNIQUEMENT, rien d'autre avant ou apres :\n"
    "Sans escalade : {\"escalade\": false, \"reponse\": \"ton message en texte brut sans HTML\"}\n"
    "Avec escalade : {\"escalade\": true, \"raison\": \"resume concis de la situation pour le commercial\"}"
)

_AI_API_URL = 'https://api.openai.com/v1/chat/completions'
_AI_MODEL = 'gpt-4o'

# Normalized phone of the Service Commercial WABA number
_SERVICE_COMMERCIAL_PHONE = '212664276055'


class TecasWhatsappAI(models.AbstractModel):
    _name = 'tecas.whatsapp.ai'
    _description = 'TECAS WhatsApp AI Handler'

    # ------------------------------------------------------------------
    # Public entry point -- called by the Odoo automation server action
    # ------------------------------------------------------------------

    @api.model
    def handle_incoming_message(self, whatsapp_msg_id):
        """Process an inbound whatsapp.message and respond via Claude AI."""
        try:
            msg = self.env['whatsapp.message'].browse(whatsapp_msg_id)
            if not msg.exists():
                return

            if not self._is_service_commercial(msg):
                return

            channel = self._get_channel(msg)
            if not channel:
                return

            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ai.openai_key'
            )
            if not api_key:
                _logger.error(
                    'TecasWhatsappAI: OpenAI API key missing -- set '
                    'ir.config_parameter key "ai.openai_key"'
                )
                return

            messages = self._build_claude_messages(channel)
            if not messages:
                return

            result = self._call_openai(messages, api_key)
            if result is None:
                return

            if not result.get('escalade', False):
                reply = (result.get('reponse') or '').strip()
                if reply:
                    self._post_whatsapp_reply(channel, reply)
            else:
                raison = result.get('raison') or 'Escalade demandee par le client.'
                salesman = self._get_next_salesman()
                if salesman:
                    self._escalate(channel, msg, raison, salesman, messages)
                else:
                    _logger.warning(
                        'TecasWhatsappAI: No salesmen configured -- '
                        'set "tecas_whatsapp_ai.salesman_ids" in System Parameters '
                        'as a comma-separated list of res.users IDs.'
                    )

        except Exception:
            _logger.exception(
                'TecasWhatsappAI: Unexpected error processing message %s',
                whatsapp_msg_id,
            )

    # ------------------------------------------------------------------
    # Account / channel helpers
    # ------------------------------------------------------------------

    def _is_service_commercial(self, msg):
        """Return True only when the message belongs to the Service Commercial WABA."""
        raw = (msg.wa_account_id.phone_number or '').strip()
        normalized = re.sub(r'[^\d]', '', raw)
        # Accept with or without leading zero: 0664276055 -> 212664276055
        if normalized.startswith('0'):
            normalized = '212' + normalized[1:]
        return normalized == _SERVICE_COMMERCIAL_PHONE

    def _get_channel(self, msg):
        """Return the discuss.channel linked to this whatsapp.message."""
        channel = msg.discuss_channel_id
        if not channel:
            _logger.warning(
                'TecasWhatsappAI: No discuss_channel_id on whatsapp.message %s',
                msg.id,
            )
            return False
        return channel

    # ------------------------------------------------------------------
    # Conversation building
    # ------------------------------------------------------------------

    def _build_claude_messages(self, channel):
        """Return the last 20 messages as a Claude-compatible list of dicts."""
        wa_msgs = self.env['whatsapp.message'].search(
            [('discuss_channel_id', '=', channel.id)],
            order='id asc',
            limit=20,
        )

        result = []
        for wa_msg in wa_msgs:
            body = self._strip_html(wa_msg.mail_message_id.body or '')
            if not body:
                continue
            role = 'user' if wa_msg.message_type == 'inbound' else 'assistant'
            # Merge consecutive same-role turns (Claude requires alternating roles)
            if result and result[-1]['role'] == role:
                result[-1]['content'] += '\n' + body
            else:
                result.append({'role': role, 'content': body})

        # Claude requires the conversation to begin with a 'user' turn
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
    # Claude API
    # ------------------------------------------------------------------

    def _call_openai(self, messages, api_key):
        """Send messages to OpenAI and return the parsed JSON dict, or None on error."""
        payload = json.dumps({
            'model': _AI_MODEL,
            'max_tokens': 512,
            'messages': [{'role': 'system', 'content': _SYSTEM_PROMPT}] + messages,
        }).encode('utf-8')

        req = urllib.request.Request(
            _AI_API_URL,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer %s' % api_key,
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
        """Extract the JSON object from Claude's reply, tolerating markdown fences."""
        # Strip ```json ... ``` fences
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        # Grab first {...} block containing "escalade"
        block = re.search(r'\{[^{}]*"escalade"[^{}]*\}', text, re.DOTALL)
        if block:
            text = block.group(0)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            _logger.error(
                'TecasWhatsappAI: Cannot parse Claude response as JSON: %s',
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

    def _get_next_salesman(self):
        """Return the next active res.users from the configured pool (round-robin)."""
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param('tecas_whatsapp_ai.salesman_ids', '')
        ids = [int(x) for x in raw.split(',') if x.strip().isdigit()]
        if not ids:
            return False

        current = int(ICP.get_param('tecas_whatsapp_ai.last_salesman_index', '-1'))
        next_idx = (current + 1) % len(ids)
        ICP.set_param('tecas_whatsapp_ai.last_salesman_index', str(next_idx))

        user = self.env['res.users'].browse(ids[next_idx])
        if user.exists() and user.active:
            return user
        # Skip inactive user -- try the rest of the pool once
        for offset in range(1, len(ids)):
            candidate_idx = (next_idx + offset) % len(ids)
            candidate = self.env['res.users'].browse(ids[candidate_idx])
            if candidate.exists() and candidate.active:
                ICP.set_param('tecas_whatsapp_ai.last_salesman_index', str(candidate_idx))
                return candidate
        return False

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(self, channel, msg, raison, salesman, messages):
        """Assign or create a CRM lead and send a briefing to the salesman."""
        partner = self._channel_partner(channel)
        lead = self._get_or_create_lead(partner, msg, salesman)
        if lead:
            self._post_lead_briefing(lead, salesman, partner, msg, raison, messages)
        else:
            # Fallback: notify salesman's partner inbox directly
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

    def _get_or_create_lead(self, partner, msg, salesman):
        """Return the most recent open lead for the contact, or create a new one."""
        if not partner:
            return False

        lead = self.env['crm.lead'].sudo().search(
            [
                ('partner_id', '=', partner.id),
                ('active', '=', True),
                ('probability', '<', 100),
            ],
            order='create_date desc',
            limit=1,
        )
        if lead:
            lead.sudo().user_id = salesman
        else:
            lead = self.env['crm.lead'].sudo().create({
                'name': 'Prospect WhatsApp -- %s' % (partner.name or msg.mobile_number or 'Inconnu'),
                'partner_id': partner.id,
                'user_id': salesman.id,
                'phone': partner.phone or msg.mobile_number or '',
                'description': (
                    'Lead genere automatiquement depuis WhatsApp Service Commercial '
                    '(+212 664-276055) par l\'assistant AI TECAS.'
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
        if partner:
            phone = partner.phone or partner.mobile or msg.mobile_number or 'N/A'
        else:
            phone = msg.mobile_number or 'N/A'

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
            body=body,
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
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
