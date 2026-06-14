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
_WA_API_BASE = 'https://graph.facebook.com/v23.0'

_PRODUCT_KEYWORDS = {'panneau', 'batterie', 'onduleur', 'materiel', 'matériel',
                     'stock', 'disponible', 'référence', 'reference'}
_PROMO_KEYWORDS   = {'promo', 'promotion', 'offre', 'remise', 'réduction', 'reduction'}
_HOURS_KEYWORDS   = {'conseiller', 'disponible', 'rappel', 'horaire', 'quand', 'urgent'}

_PROFILE_KEYWORDS_RE = re.compile(
    r'\b(Revendeur|Reseller|موزع)\b|\b(Installateur|Installer|مركب|مثبت)',
    re.IGNORECASE,
)

# No longer used for classification but kept for potential future reference

_ESCALATION_CLOSING_PATTERNS = [
    'conseiller va vous contacter',
    'equipe va vous contacter',
    'merci pour vos informations',
    'prendre contact avec vous',
    'vous serez contact',
    'nous vous contacterons',
    'vous contacter dans les plus brefs',
    'notre equipe prendra contact',
]


_SERVICE_LABELS = {
    'solar_installation':   'Installation solaire',
    'pumping':              'Pompage solaire agricole',
    'industrial':           'Projet industriel/professionnel',
    'equipment_panels':     'Achat matériel — Panneaux solaires',
    'equipment_inverters':  'Achat matériel — Onduleurs',
    'equipment_batteries':  'Achat matériel — Batteries',
    'equipment_structure':  'Achat matériel — Structures de fixation',
    'equipment_cables':     'Achat matériel — Câbles et accessoires',
    'equipment_multi':      'Achat matériel — Commande mixte',
    'b2b_partner':          'Partenaire B2B (Installateur/Revendeur)',
    'sav':                  'SAV',
    'advisor':              'Prise de contact conseiller',
    # legacy codes — kept for backward compatibility
    'residential':          'Installation solaire',
    'quick_quote':          'Devis rapide',
    'showroom':             'Visite showroom',
    'revendeur':            'Revendeur',
    'installateur':         'Installateur',
}

_COMPANY_SIGNATURE = (
    "\n\n"
    "📍 Showroom TECAS Énergie Solaire\n"
    "Lot N°10 Lotissement Polygone\n"
    "Route des Zenata km 10.5, Zone Industrielle Ain Sebaa\n"
    "Casablanca – Maroc\n\n"
    "📞 +212 520 854 141\n"
    "📧 info@tecas.ma\n"
    "🌐 tecas.ma\n\n"
    "🌞 Venez visiter notre showroom et découvrir nos installations solaires en fonctionnement réel."
)

# Morocco is UTC+1 year-round (no DST)
_TZ_MOROCCO = timezone(timedelta(hours=1))


class WhatsappAIBot(models.AbstractModel):
    _name = 'whatsapp.ai.bot'
    _description = 'WhatsApp AI Bot Handler'

    _VOICE_FALLBACK_FR = (
        "Bonjour ! Bienvenue chez TECAS Energie Solaire.\n\n"
        "Je ne peux pas traiter les messages vocaux. "
        "Veuillez taper votre demande par écrit.\n\n"
        "Comment puis-je vous aider ?\n"
        "1. Installation solaire\n"
        "2. Pompage solaire agricole\n"
        "3. Projet industriel ou professionnel\n"
        "4. Achat de matériel solaire\n"
        "5. Installateur / Revendeur\n"
        "6. Service Après-Vente (SAV)\n"
        "7. Contacter un conseiller"
    )

    @api.model
    def handle_incoming_message(self, whatsapp_msg_id):
        """Process an inbound whatsapp.message and respond via OpenAI."""
        config = self.env['whatsapp.ai.bot.config'].sudo().get_singleton()
        if not config.active:
            return

        try:
            msg = self.env['whatsapp.message'].browse(whatsapp_msg_id)
            if not msg.exists():
                _logger.warning('WhatsappAIBot: msg %s does not exist', whatsapp_msg_id)
                return

            if not self._is_service_commercial(msg, config):
                return

            channel = self._get_channel(msg)
            if not channel:
                return

            if self._human_has_taken_over(channel, config):
                _logger.info(
                    'WhatsappAIBot: channel %s — human agent active, AI skipped',
                    channel.id,
                )
                return

            # Voice / media message — no text body → send fixed French welcome directly
            msg_body = self._strip_html(msg.mail_message_id.body or '')
            if not msg_body:
                _logger.info('WhatsappAIBot: voice/media message on channel %s — sending French welcome', channel.id)
                self._post_whatsapp_reply(channel, self._VOICE_FALLBACK_FR)
                return

            if not config.openai_api_key:
                _logger.error(
                    'WhatsappAIBot: OpenAI API key not set -- configure it in WhatsApp > Bot'
                )
                return

            messages = self._build_messages(channel)
            if not messages:
                _logger.warning(
                    'WhatsappAIBot: msg %s -- no conversation history for channel %s',
                    whatsapp_msg_id, channel.id,
                )
                return

            context_block = self._build_context_block(channel, messages)

            # If the last bot message was an escalation closing, force a full reset
            if self._was_escalation_closing(messages):
                _logger.info('WhatsappAIBot: post-escalation reset injected for channel %s', channel.id)
                context_block = (context_block or '') + (
                    '\n\n[INSTRUCTION PRIORITAIRE — RESET COMPLET] '
                    'Ta derniere reponse etait une cloture d\'escalade. '
                    'Le present message du client est un TOUT PREMIER CONTACT. '
                    'Reponds UNIQUEMENT avec un message de bienvenue chaleureux '
                    'suivi de la question de profil : '
                    '1. Client / 2. Revendeur / 3. Installateur. '
                    'N\'utilise pas le contexte, le flux ou l\'option de la conversation precedente.'
                )

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
                        'WhatsappAIBot: reusing lead=%s salesman=%s for partner=%s',
                        existing_lead.id, salesman.id, partner.id if partner else None,
                    )
                else:
                    salesman = self._get_next_salesman(config)
                    _logger.info(
                        'WhatsappAIBot: no existing lead/salesman, round-robin -> salesman=%s',
                        salesman.id if salesman else None,
                    )
                if salesman:
                    self._escalate(channel, msg, raison, salesman, messages, service)
                else:
                    _logger.warning(
                        'WhatsappAIBot: No salesmen configured -- add users in WhatsApp > Bot'
                    )
                if reply:
                    self._post_whatsapp_reply(channel, reply + _COMPANY_SIGNATURE, is_escalation=True)

        except Exception:
            _logger.exception(
                'WhatsappAIBot: Unexpected error processing message %s',
                whatsapp_msg_id,
            )

    # ------------------------------------------------------------------
    # Account / channel helpers
    # ------------------------------------------------------------------

    def _is_service_commercial(self, msg, config):
        """Return True only when the message belongs to the configured WhatsApp account."""
        if not config.wa_account_id:
            _logger.warning(
                'WhatsappAIBot: No WhatsApp account selected in Bot configuration'
            )
            return False
        return msg.wa_account_id.id == config.wa_account_id.id

    def _get_channel(self, msg):
        """Return the discuss.channel linked to this whatsapp.message."""
        mail_msg = msg.mail_message_id
        if not mail_msg or mail_msg.model != 'discuss.channel':
            _logger.warning(
                'WhatsappAIBot: No discuss.channel linked to whatsapp.message %s',
                msg.id,
            )
            return False
        channel = self.env['discuss.channel'].browse(mail_msg.res_id)
        if not channel.exists():
            _logger.warning(
                'WhatsappAIBot: discuss.channel %s not found for whatsapp.message %s',
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
        hours = config.human_takeover_hours
        if hours == 0:
            return False

        bot_partner_id = self.env.ref('base.partner_root').id
        customer_partner = self._channel_partner(channel)
        excluded_ids = [bot_partner_id]
        if customer_partner:
            excluded_ids.append(customer_partner.id)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
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

    # ------------------------------------------------------------------
    # Interactive message helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_header_and_list(reply):
        """Return (header_str, [(id_str, title_str), ...]) splitting at the first numbered item.

        Handles three AI output formats:
        - One option per line:   "1. Option A\\n2. Option B"
        - Multiple per line:     "1. A  2. B  3. C  4. D  5. E"
        - Option inside header:  "a) Question : 1. A\\n2. B\\n3. C"
        Strips '0.' items and '(Repondez...)' footers.
        """
        # Extracts all "N. text" items from within a single line
        _inline_re = re.compile(
            r'([1-9][0-9]?)[\.。)]\s+(.+?)(?=\s+[1-9][0-9]?[\.。)]|\s*$)'
        )

        def _items_from_line(s):
            found = _inline_re.findall(s)
            return [(num, text.strip()) for num, text in found] if found else []

        lines = reply.split('\n')
        first_idx = None
        for i, line in enumerate(lines):
            if re.match(r'^\s*[1-9][0-9]?\s*[\.。)]\s*\S', line):
                first_idx = i
                break

        if first_idx is None:
            # No line starts with a number — scan for inline "1. option" inside any line
            for i, line in enumerate(lines):
                s = line.strip()
                if not s or re.match(r'^\(R[ée]pondez', s):
                    continue
                first_pos = re.search(r'(?<!\d)\b1[\.。)]\s', s)
                if first_pos:
                    inline_items = _inline_re.findall(s[first_pos.start():])
                    if len(inline_items) >= 2:
                        question_part = s[:first_pos.start()].rstrip(':').strip()
                        before = [
                            l.strip() for l in lines[:i]
                            if l.strip() and not re.match(r'^\(R[ée]pondez', l.strip())
                        ]
                        if question_part:
                            before.append(question_part)
                        return '\n'.join(before).strip(), [(n, t.strip()) for n, t in inline_items]
            return reply.strip(), []

        header_lines = [
            l.strip() for l in lines[:first_idx]
            if l.strip() and not re.match(r'^\(R[ée]pondez', l.strip())
        ]
        items = []
        for line in lines[first_idx:]:
            s = line.strip()
            if not s or re.match(r'^\(R[ée]pondez', s):
                continue
            items.extend(_items_from_line(s))

        # If list doesn't start at 1, the last header line may contain inline "1. Option"
        # (e.g. "a) Puissance : 1. 550W" when options 2+ are on separate lines)
        if items and items[0][0] != '1' and header_lines:
            last = header_lines[-1]
            m2 = re.search(r':\s*(1[\.。)]\s*(.+))$', last)
            if m2:
                option_text = re.split(r'\s+\d', m2.group(2))[0].strip()
                items.insert(0, ('1', option_text))
                header_lines[-1] = last[:m2.start()].rstrip(':').strip()
                if not header_lines[-1]:
                    header_lines.pop()

        header = '\n'.join(header_lines).strip()
        return header, items

    @staticmethod
    def _clean_label(text, max_len):
        """Strip parenthetical notes and truncate to max_len characters."""
        clean = re.split(r'\s*[\(（/]', text)[0].strip()
        if not clean:
            clean = text.strip()
        if len(clean) <= max_len:
            return clean
        truncated = clean[:max_len].rsplit(' ', 1)[0]
        return truncated if len(truncated) >= max_len // 2 else clean[:max_len]

    def _classify_reply(self, reply):
        """Return 'profile' | 'client_menu' | 'plain' based on numbered list structure.

        2-3 items  → interactive quick-reply buttons ('profile' path)
        4-10 items → interactive list message ('client_menu' path)
        0-1 items  → plain text with restart button
        """
        _, items = self._split_header_and_list(reply)
        n = len(items)
        if 2 <= n <= 3:
            return 'profile'
        if n >= 4:
            return 'client_menu'
        return 'plain'

    def _log_outbound_for_history(self, channel, body):
        """Create mail.message (comment) + whatsapp.message (outbound) for AI history.

        Used when the WhatsApp send is done via direct API (interactive messages) so
        Odoo does not duplicate the text send but still tracks the exchange for context.
        """
        mail_msg = channel.sudo().message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=self.env.ref('base.partner_root').id,
        )
        if mail_msg:
            self.env['whatsapp.message'].sudo().create({
                'mail_message_id': mail_msg.id,
                'mobile_number': '+' + str(getattr(channel, 'whatsapp_number', '') or ''),
                'message_type': 'outbound',
                'wa_account_id': channel.wa_account_id.id if channel.wa_account_id else False,
                'state': 'sent',
            })

    def _send_interactive_profile(self, channel, header, items):
        """Send a 3-button interactive message for the Client/Revendeur/Installateur choice."""
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return
        body_text = (header or 'Pour mieux vous orienter, êtes-vous :')[:1024]
        buttons = [
            {'type': 'reply', 'reply': {'id': iid, 'title': self._clean_label(title, 20)}}
            for iid, title in items[:3]
        ]
        if not buttons:
            return
        payload = json.dumps({
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': number,
            'type': 'interactive',
            'interactive': {
                'type': 'button',
                'body': {'text': body_text},
                'action': {'buttons': buttons},
            },
        }).encode('utf-8')
        self._wa_post(account, payload)

    def _send_interactive_list_menu(self, channel, header, items):
        """Send a list-type interactive message for the 8-option client menu.

        Adds '↩ Recommencer' as the last row (id='0') so the restart button is built in.
        """
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return
        body_text = (header or 'Comment puis-je vous aider ?')[:1024]
        rows = [
            {'id': iid, 'title': self._clean_label(title, 24)}
            for iid, title in items[:9]
        ]
        rows.append({'id': '0', 'title': 'Recommencer'})
        payload = json.dumps({
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': number,
            'type': 'interactive',
            'interactive': {
                'type': 'list',
                'body': {'text': body_text},
                'action': {
                    'button': 'Voir les options',
                    'sections': [{'title': 'Services', 'rows': rows}],
                },
            },
        }).encode('utf-8')
        self._wa_post(account, payload)

    def _wa_post(self, account, payload):
        """POST payload to the WhatsApp Business API for the given account."""
        token = account.sudo().token
        req = urllib.request.Request(
            '%s/%s/messages' % (_WA_API_BASE, account.phone_uid),
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer %s' % token,
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()

    def _was_escalation_closing(self, messages):
        """Return True if the last assistant message is an escalation closing."""
        for msg in reversed(messages):
            if msg['role'] == 'assistant':
                content_lower = (
                    msg['content'].lower()
                    .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
                    .replace('à', 'a').replace('â', 'a')
                )
                return any(p in content_lower for p in _ESCALATION_CLOSING_PATTERNS)
        return False

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
                _logger.warning('WhatsappAIBot: context — product catalog query failed')

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
                _logger.warning('WhatsappAIBot: context — promotions query failed')

        # 3. Customer profile — only inject phone (already known from WhatsApp, never ask again).
        # Name and city are NOT injected here so the AI always asks for them in the branch flow.
        try:
            partner = self._channel_partner(channel)
            if partner:
                phone = partner.phone or getattr(partner, 'mobile', None)
                if phone:
                    blocks_priority.append((
                        'client_profile',
                        'PROFIL CLIENT :\n'
                        '- Telephone WhatsApp : %s (deja connu, ne JAMAIS le redemander)' % phone,
                    ))
        except Exception:
            _logger.warning('WhatsappAIBot: context — customer profile query failed')

        # 4. Existing CRM lead — always checked
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
            _logger.warning('WhatsappAIBot: context — CRM lead query failed')

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
                _logger.warning('WhatsappAIBot: context — business hours computation failed')

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
            _logger.error('WhatsappAIBot: OpenAI HTTP %s -- %s', exc.code, body[:500])
        except urllib.error.URLError as exc:
            _logger.error('WhatsappAIBot: OpenAI network error -- %s', exc.reason)
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
                'WhatsappAIBot: Cannot parse AI response as JSON: %s',
                text[:400],
            )
            return None

    # ------------------------------------------------------------------
    # Reply posting
    # ------------------------------------------------------------------

    def _post_whatsapp_reply(self, channel, reply, is_escalation=False):
        """Post the AI-generated reply to the WhatsApp discuss channel.

        - Profile question (2-3 choices) → interactive button message
        - Menu (4+ choices)              → interactive list message with built-in restart row
        - Escalation closing             → plain text + "Recommencer" button
        - Mid-flow question              → plain text only (no button — avoids accidental restart)
        """
        msg_class = self._classify_reply(reply)
        try:
            if msg_class == 'profile':
                header, items = self._split_header_and_list(reply)
                self._log_outbound_for_history(channel, reply)
                self._send_interactive_profile(channel, header, items)
            elif msg_class == 'client_menu':
                header, items = self._split_header_and_list(reply)
                self._log_outbound_for_history(channel, reply)
                self._send_interactive_list_menu(channel, header, items)
            else:
                self._log_outbound_for_history(channel, reply)
                if is_escalation:
                    self._send_plain_with_restart(channel, reply)
                else:
                    self._send_pure_text(channel, reply)
        except Exception:
            _logger.exception('WhatsappAIBot: Failed to post WhatsApp reply.')

    def _send_plain_with_restart(self, channel, reply):
        """Send reply text as an interactive button message with an ↩ Recommencer quick-reply.

        Combines the text and the restart button into one bubble so no "─" separator appears.
        """
        try:
            account = channel.wa_account_id
            if not account or not account.phone_uid:
                return
            number = str(getattr(channel, 'whatsapp_number', '') or '')
            if not number:
                return
            body_text = reply[:1024]
            if len(reply) > 1024:
                body_text = reply[:1021] + '…'
            payload = json.dumps({
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': number,
                'type': 'interactive',
                'interactive': {
                    'type': 'button',
                    'body': {'text': body_text},
                    'action': {
                        'buttons': [{'type': 'reply', 'reply': {'id': '0', 'title': 'Recommencer'}}],
                    },
                },
            }).encode('utf-8')
            self._wa_post(account, payload)
            _logger.info('WhatsappAIBot: plain+restart button sent for channel %s', channel.id)
        except Exception:
            _logger.warning(
                'WhatsappAIBot: Failed to send plain+restart for channel %s', channel.id,
                exc_info=True,
            )

    def _send_pure_text(self, channel, reply):
        """Send reply as a plain WhatsApp text message with no interactive elements."""
        try:
            account = channel.wa_account_id
            if not account or not account.phone_uid:
                return
            number = str(getattr(channel, 'whatsapp_number', '') or '')
            if not number:
                return
            body_text = reply[:4096]
            payload = json.dumps({
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': number,
                'type': 'text',
                'text': {'body': body_text},
            }).encode('utf-8')
            self._wa_post(account, payload)
        except Exception:
            _logger.warning(
                'WhatsappAIBot: Failed to send pure text for channel %s', channel.id,
                exc_info=True,
            )

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
            'WhatsappAIBot: _find_existing_lead partner=%s phone=%s -> lead=%s user_id=%s',
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
