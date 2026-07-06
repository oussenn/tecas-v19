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

# Gap in hours between two messages that marks a new session boundary.
# Any silence >= this value means the next message starts a fresh context.
_SESSION_GAP_HOURS = 4

# Product-related triggers (French + Darija latin + Arabic)
_PRODUCT_KEYWORDS = {
    'panneau', 'panneaux', 'panel', 'batterie', 'batteries', 'onduleur', 'onduleurs',
    'materiel', 'matériel', 'stock', 'disponible', 'référence', 'reference',
    'pompe', 'cable', 'câble', 'structure', 'kit', 'jinko', 'canadian', 'huawei',
    'deye', 'sungrow', 'lithium', 'lifepo', 'gel', 'watt', 'kwc', 'solaire',
    'variateur', 'variateurs', 'vfd', 'must', 'solplanet', 'solax',
    # Darija intent keywords (I want/need → likely product query)
    'kasni', 'khassni', 'bghit', 'bghyt', 'bghi', 'kaini', 'dyl', 'dyalhom',
    # Darija for inverter/VFD (common in pompage context)
    'fachi', 'fishi', 'fachi', 'محول',
    # Arabic product keywords
    'لوحة', 'الواح', 'ألواح', 'بطارية', 'بطاريات', 'انفرتر', 'منظومة', 'طاقة', 'شمسية',
}
# Price-related triggers including Darija latin + Arabic script
_PRICE_KEYWORDS = {
    'prix', 'price', 'tarif', 'tarifs', 'combien', 'bch7al', 'bchhal', 'chhal',
    'thaman', 'cout', 'coût', 'kdam', 'b7al', 'wach3and', 'coute', 'coûte',
    'valent', 'vaut', 'cher', 'budget',
    # Arabic script price keywords
    'تمن', 'تمان', 'ثمن', 'شحال', 'بشحال', 'التمن', 'الثمن', 'السعر', 'سعر', 'بكام',
}
_HOURS_KEYWORDS = {'conseiller', 'disponible', 'rappel', 'horaire', 'quand', 'urgent'}

# Patterns that identify an escalation closing in bot messages
_ESCALATION_CLOSING_PATTERNS = [
    'conseiller va vous contacter',
    'equipe va vous contacter',
    'merci pour vos informations',
    'prendre contact avec vous',
    'vous serez contact',
    'nous vous contacterons',
    'vous contacter dans les plus brefs',
    'notre equipe prendra contact',
    # English
    'advisor will contact you',
    'team will contact you',
    'thank you for your information',
    # Arabic
    'سيتصل بك',
    'سنتواصل معك',
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
    'residential':          'Installation solaire',
    'quick_quote':          'Devis rapide',
    'showroom':             'Visite showroom',
    'revendeur':            'Revendeur',
    'installateur':         'Installateur',
}

# Code-generated escalation closings — guaranteed correct language, no AI drift
_ESCALATION_CLOSINGS = {
    'anglais': (
        "Thank you {name}! 🙏 A TECAS advisor will get in touch with you very shortly.\n"
        "We look forward to helping you with your solar project!"
    ),
    'arabe': (
        "شكراً {name}! 🙏 سيتصل بك أحد مستشاري TECAS قريباً جداً.\n"
        "نتطلع إلى مساعدتك في مشروعك الشمسي!"
    ),
    'fr': (
        "Merci {name} ! 🙏 Un conseiller TECAS va vous contacter très prochainement.\n"
        "Nous avons hâte de vous accompagner dans votre projet solaire !"
    ),
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

# First recall (after _NUDGE_1_DELAY_HOURS of client silence)
_NUDGE_MESSAGES_1 = {
    'fr':      "Êtes-vous toujours là ? 😊\nN'hésitez pas à continuer, je suis là pour vous aider !",
    'anglais': "Are you still there? 😊\nFeel free to continue — I'm here to help!",
    'arabe':   "هل لا تزال هناك؟ 😊\nلا تتردد في المتابعة، أنا هنا للمساعدة!",
}
# Second / final recall (after _NUDGE_2_DELAY_HOURS more of silence)
_NUDGE_MESSAGES_2 = {
    'fr':      "Bonjour 👋 Je reviens vers vous une dernière fois — souhaitez-vous qu'on avance sur votre projet solaire ? Je reste à votre disposition !",
    'anglais': "Hello 👋 Just following up one last time — would you like to move forward with your solar project? I'm here whenever you're ready!",
    'arabe':   "مرحبًا 👋 أتواصل معكم للمرة الأخيرة — هل ترغبون في المضي قدمًا في مشروعكم الشمسي؟ أنا في خدمتكم!",
}

# Two-stage follow-up schedule.
# Stage 1: first recall fires 4h after the bot's last message with no client reply.
# Stage 2: second recall fires 20h after the first recall (≈24h after the bot's message).
_NUDGE_1_DELAY_HOURS = 4
_NUDGE_2_DELAY_HOURS = 20
# Cron only scans channels active within this window — must exceed 4h + 20h.
_NUDGE_LOOKBACK_HOURS = 26

_TZ_MOROCCO = timezone(timedelta(hours=1))


class WhatsappAIBot(models.AbstractModel):
    _name = 'whatsapp.ai.bot'
    _description = 'WhatsApp AI Bot Handler'

    _VOICE_FALLBACK_FR = (
        "Bonjour ! Bienvenue chez TECAS Énergie Solaire. 🌞\n\n"
        "Je ne peux pas traiter les messages vocaux ou vidéo. "
        "Veuillez écrire votre message ou envoyer une photo, et je vous répondrai avec plaisir !"
    )

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_current_session_messages(messages):
        """Return only messages from the current session — after the last escalation closing.

        Prevents language / context from a previous completed session bleeding into
        a new one when the same channel is reused (return customer).
        """
        last_esc = -1
        for i, msg in enumerate(messages):
            if msg['role'] == 'assistant':
                content_lower = (
                    msg['content'].lower()
                    .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
                    .replace('à', 'a').replace('â', 'a')
                )
                if any(p in content_lower for p in _ESCALATION_CLOSING_PATTERNS):
                    last_esc = i
        return messages[last_esc + 1:] if last_esc >= 0 else messages

    @staticmethod
    def _detect_active_language(session_messages):
        """Detect active language — client's last message takes priority.

        Returns 'anglais' or 'arabe'; None means French/Darija-French (no injection needed).
        Call with _get_current_session_messages() result, never the full history.
        """
        # 1. Client's last message is ground truth — check it first
        for msg in reversed(session_messages):
            if msg['role'] == 'user':
                content = msg['content']
                if isinstance(content, list):
                    # Vision format — extract text parts
                    content = ' '.join(
                        p.get('text', '') for p in content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    )
                arabic_chars = sum(1 for c in content if '؀' <= c <= 'ۿ')
                if arabic_chars > 3:
                    return 'arabe'
                c = content.lower()
                # High-confidence English-only phrases — one match is enough
                english_high = [
                    'do you', 'can you', 'i need', 'i want', 'i have', 'i am',
                    'how much', 'what is', 'what are', 'how are', 'is it',
                    'these', 'those', 'hello', 'hi ', 'please', 'thank',
                    'good morning', 'good evening', 'available', 'interested',
                ]
                if any(w in c for w in english_high):
                    return 'anglais'
                # Lower-confidence — need 2+ matches
                english_low = [' the ', ' and ', ' your ', ' for ', ' with ', ' are ', ' can ', ' my ']
                if sum(1 for w in english_low if w in c) >= 2:
                    return 'anglais'
                # Last message is French/Darija — no language lock needed
                return None

        # 2. No user messages yet: infer from recent bot messages (Arabic consistency)
        bot_msgs = [m['content'] for m in session_messages[-4:] if m['role'] == 'assistant']
        if not bot_msgs:
            return None
        combined = ' '.join(bot_msgs)
        if not combined:
            return None
        arabic_chars = sum(1 for c in combined if '؀' <= c <= 'ۿ')
        if arabic_chars > 10 and arabic_chars / len(combined) > 0.08:
            return 'arabe'
        english_markers = [
            ' the ', ' and ', ' your ', ' our ', ' for ', ' with ', ' you ',
            'hello', 'welcome', 'solar', 'panel', 'please', 'thank',
        ]
        if sum(1 for w in english_markers if w in combined.lower()) >= 3:
            return 'anglais'
        return None

    def _extract_images(self, msg):
        """Return list of (mimetype, base64_str) for image attachments on this message."""
        images = []
        try:
            for att in msg.mail_message_id.sudo().attachment_ids:
                if not att.mimetype or not att.mimetype.startswith('image/'):
                    continue
                if not att.datas:
                    continue
                b64 = att.datas
                if isinstance(b64, bytes):
                    b64 = b64.decode('utf-8')
                images.append((att.mimetype, b64))
                if len(images) >= 3:
                    break
        except Exception:
            _logger.warning('WhatsappAIBot: failed to extract images from msg %s', msg.id, exc_info=True)
        return images

    @staticmethod
    def _inject_images(session_msgs, msg_body, images):
        """Replace the last user message with a vision-format message (text + images).

        Must be called AFTER language detection and context building, since those
        expect string content. After injection the last user message content becomes a list.
        """
        if not images:
            return session_msgs

        # Ensure the current message is in session_msgs (skipped by _build_messages if body was empty)
        msgs = list(session_msgs)
        if not msgs or msgs[-1]['role'] != 'user':
            msgs.append({'role': 'user', 'content': msg_body or '[Image]'})

        # Find the last user message and replace its content with vision format
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i]['role'] == 'user':
                text = msgs[i]['content'] if isinstance(msgs[i]['content'], str) else (msg_body or '[Image]')
                content_parts = [{'type': 'text', 'text': text or '[Image]'}]
                for mimetype, b64 in images:
                    content_parts.append({
                        'type': 'image_url',
                        'image_url': {
                            'url': 'data:%s;base64,%s' % (mimetype, b64),
                            'detail': 'auto',
                        },
                    })
                msgs[i] = {'role': 'user', 'content': content_parts}
                return msgs

        return msgs

    @staticmethod
    def _is_real_partner_name(name):
        """Return True if name looks like a real person/company name, not auto-generated."""
        if not name or len(name.strip()) < 3:
            return False
        if re.match(r'^[\+\d\s\-\(\)\.]+$', name.strip()):
            return False
        return True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

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
                _logger.info('WhatsappAIBot: channel %s — human agent active, AI skipped', channel.id)
                return

            msg_body = self._strip_html(msg.mail_message_id.body or '')
            images = self._extract_images(msg)

            if not msg_body and not images:
                _logger.info('WhatsappAIBot: voice/unsupported media on channel %s', channel.id)
                self._post_whatsapp_reply(channel, self._VOICE_FALLBACK_FR)
                return

            if not config.openai_api_key:
                _logger.error('WhatsappAIBot: OpenAI API key not set')
                return

            messages = self._build_messages(channel)
            if not messages and not images:
                _logger.warning('WhatsappAIBot: no conversation history for channel %s', channel.id)
                return

            session_msgs = self._get_current_session_messages(messages)
            lang = self._detect_active_language(session_msgs)
            context_block = self._build_context_block(channel, messages, session_msgs, lang)

            if self._was_escalation_closing(messages):
                _logger.info('WhatsappAIBot: post-escalation reset for channel %s', channel.id)
                context_block = (context_block or '') + (
                    '\n\n[RESET] La derniere reponse du bot etait une cloture d\'escalade. '
                    'Ce message est un NOUVEAU contact. '
                    'Accueillir chaleureusement et demander comment aider — PAS de menu numerote. '
                    'Utiliser SALUTATION_NOM si present dans le contexte. '
                    'Respecter LANGUE ACTIVE.'
                )

            # Inject images after all text processing (language detection, context building)
            if images:
                session_msgs = self._inject_images(session_msgs, msg_body, images)
                _logger.info('WhatsappAIBot: %d image(s) injected for channel %s', len(images), channel.id)

            result = self._call_openai(session_msgs, config, context_block)
            if result is None:
                return

            self._save_client_info(channel, result)

            service = (result.get('service') or 'unknown').strip()

            if not result.get('escalade', False):
                reply = (result.get('reponse') or '').strip()
                if reply:
                    self._post_whatsapp_reply(channel, reply)
            else:
                # Language-correct closing generated by code — not by the AI
                client_name = (result.get('client_name') or '').strip() or 'cher client'
                closing_tpl = _ESCALATION_CLOSINGS.get(lang or 'fr', _ESCALATION_CLOSINGS['fr'])
                closing = closing_tpl.format(name=client_name)

                raison = (result.get('raison') or 'Escalade demandee par le client.').strip()
                partner = self._channel_partner(channel)
                existing_lead = self._find_existing_lead(partner)

                if existing_lead and existing_lead.user_id:
                    salesman = existing_lead.user_id
                else:
                    salesman = self._get_next_salesman(config)

                if salesman:
                    self._escalate(channel, msg, raison, salesman, messages, service)
                else:
                    _logger.warning('WhatsappAIBot: No salesmen configured')

                self._post_whatsapp_reply(channel, closing + _COMPANY_SIGNATURE, is_escalation=True)

        except Exception:
            _logger.exception('WhatsappAIBot: Unexpected error processing message %s', whatsapp_msg_id)

    # ------------------------------------------------------------------
    # Account / channel helpers
    # ------------------------------------------------------------------

    def _is_service_commercial(self, msg, config):
        if not config.wa_account_ids:
            _logger.warning('WhatsappAIBot: No WhatsApp account selected in Bot configuration')
            return False
        return msg.wa_account_id.id in config.wa_account_ids.ids

    def _get_channel(self, msg):
        mail_msg = msg.mail_message_id
        if not mail_msg or mail_msg.model != 'discuss.channel':
            _logger.warning('WhatsappAIBot: No discuss.channel linked to whatsapp.message %s', msg.id)
            return False
        channel = self.env['discuss.channel'].browse(mail_msg.res_id)
        if not channel.exists():
            _logger.warning('WhatsappAIBot: discuss.channel %s not found', mail_msg.res_id)
            return False
        return channel

    def _human_has_taken_over(self, channel, config):
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

    def _build_messages(self, channel):
        """Return messages from the current session as an OpenAI-compatible list.

        Session boundary: any silence gap >= _SESSION_GAP_HOURS hours between consecutive
        messages resets the session — messages before the gap are discarded. This prevents
        name/city/intent collected in a previous conversation from prematurely triggering
        escalation in a new one.
        """
        wa_msgs = self.env['whatsapp.message'].search(
            [
                ('mail_message_id.model', '=', 'discuss.channel'),
                ('mail_message_id.res_id', '=', channel.id),
            ],
            order='id desc',
            limit=20,
        )
        wa_msgs = wa_msgs.sorted('id')

        # Find the start of the current session (most recent gap >= _SESSION_GAP_HOURS)
        session_start = 0
        for i in range(len(wa_msgs) - 1, 0, -1):
            prev_date = wa_msgs[i - 1].create_date
            curr_date = wa_msgs[i].create_date
            if prev_date and curr_date:
                gap_hours = (curr_date - prev_date).total_seconds() / 3600.0
                if gap_hours >= _SESSION_GAP_HOURS:
                    session_start = i
                    break

        wa_msgs = wa_msgs[session_start:]

        result = []
        for wa_msg in wa_msgs:
            body = self._strip_html(wa_msg.mail_message_id.body or '')
            if not body:
                continue
            role = 'user' if wa_msg.message_type == 'inbound' else 'assistant'
            if result and result[-1]['role'] == role:
                result[-1]['content'] += '\n' + body
            else:
                result.append({'role': role, 'content': body})
        while result and result[0]['role'] != 'user':
            result.pop(0)
        return result

    @staticmethod
    def _strip_html(text):
        text = re.sub(r'<[^>]+>', '', text or '')
        return (
            text
            .replace('&amp;', '&').replace('&lt;', '<')
            .replace('&gt;', '>').replace('&nbsp;', ' ')
        ).strip()

    def _was_escalation_closing(self, messages):
        for msg in reversed(messages):
            if msg['role'] == 'assistant':
                content_lower = (
                    msg['content'].lower()
                    .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
                    .replace('à', 'a').replace('â', 'a')
                )
                return any(p in content_lower for p in _ESCALATION_CLOSING_PATTERNS)
        return False

    # ------------------------------------------------------------------
    # Context block
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(text):
        """Normalize French/Darija text for keyword matching."""
        return (
            text.lower()
            .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
            .replace('à', 'a').replace('â', 'a')
            .replace('ô', 'o').replace('û', 'u').replace('î', 'i')
            .replace('ç', 'c')
        )

    def _build_context_block(self, channel, messages, session_msgs, lang):
        """Build a context string injected into the system prompt for this request."""
        recent_raw = ' '.join(m['content'] for m in session_msgs[-5:])
        recent_norm = self._norm(recent_raw)
        recent_words = set(recent_norm.split())

        parts = []

        # 0. Language lock
        if lang:
            parts.append(
                'LANGUE ACTIVE : %s\n'
                'REGLE ABSOLUE : Utiliser uniquement cette langue. '
                'Ne jamais revenir au francais.' % lang
            )

        # 1. Client profile + history
        try:
            partner = self._channel_partner(channel)
            if partner:
                profile = self._build_profile_block(partner, session_msgs)
                if profile:
                    parts.append(profile)
                history = self._fetch_client_history(partner)
                if history:
                    parts.append(history)
        except Exception:
            _logger.warning('WhatsappAIBot: context — profile/history query failed')

        # 2. Product catalog with prices (triggered by product OR price keywords)
        wants_products = bool((_PRODUCT_KEYWORDS | _PRICE_KEYWORDS) & recent_words)
        if wants_products:
            try:
                products_block = self._fetch_products_with_prices(recent_norm)
                if products_block:
                    parts.append(products_block)
            except Exception:
                _logger.warning('WhatsappAIBot: context — product catalog query failed')

        # 3. Business hours (keyword-triggered)
        if _HOURS_KEYWORDS & recent_words:
            try:
                parts.append(self._build_hours_block())
            except Exception:
                _logger.warning('WhatsappAIBot: context — business hours failed')

        if not parts:
            return ''

        # Enforce character budget — truncate last block if needed
        CHAR_BUDGET = 2800
        output = []
        used = 0
        for block in parts:
            if used + len(block) + 2 <= CHAR_BUDGET:
                output.append(block)
                used += len(block) + 2
            else:
                remaining = CHAR_BUDGET - used
                if remaining > 60:
                    # Keep as many lines as fit
                    kept = []
                    for line in block.split('\n'):
                        if used + len('\n'.join(kept)) + len(line) + 1 <= CHAR_BUDGET:
                            kept.append(line)
                        else:
                            kept.append('(suite tronquée)')
                            break
                    output.append('\n'.join(kept))
                break

        return '\n\n---\nCONTEXTE TEMPS RÉEL :\n' + '\n\n'.join(output) if output else ''

    def _build_profile_block(self, partner, session_msgs):
        """Build client profile context lines."""
        phone = partner.phone or getattr(partner, 'mobile', None)
        lines = ['PROFIL CLIENT :']
        if phone:
            lines.append('- TEL : %s (connu, ne pas redemander)' % phone)
        if self._is_real_partner_name(partner.name):
            session_user_count = sum(1 for m in session_msgs if m['role'] == 'user')
            if session_user_count <= 1:
                lines.append('- SALUTATION_NOM : %s' % partner.name)
            else:
                lines.append('- NOM_CONNU : %s' % partner.name)
        city = getattr(partner, 'city', None)
        if city:
            lines.append('- VILLE_CONNUE : %s' % city)
        return '\n'.join(lines) if len(lines) > 1 else ''

    def _fetch_client_history(self, partner):
        """Fetch existing CRM leads and sale orders for context."""
        lines = []
        try:
            leads = self.env['crm.lead'].sudo().search(
                [('partner_id', '=', partner.id), ('active', '=', True)],
                order='create_date desc', limit=3,
            )
            if leads:
                lines.append('HISTORIQUE CRM :')
                for lead in leads:
                    date = lead.create_date.strftime('%d/%m/%Y') if lead.create_date else '?'
                    stage = lead.stage_id.name if lead.stage_id else 'En cours'
                    lines.append('- %s | %s | %s' % (lead.name, date, stage))
        except Exception:
            _logger.warning('WhatsappAIBot: context — CRM leads query failed')
        try:
            orders = self.env['sale.order'].sudo().search(
                [('partner_id', '=', partner.id), ('state', 'not in', ['draft', 'cancel'])],
                order='date_order desc', limit=3,
            )
            if orders:
                lines.append('COMMANDES PRECEDENTES :')
                for order in orders:
                    date = order.date_order.strftime('%d/%m/%Y') if order.date_order else '?'
                    lines.append('- %s | %s | %.0f MAD' % (order.name, date, order.amount_total))
        except Exception:
            _logger.warning('WhatsappAIBot: context — sale orders query failed')
        return '\n'.join(lines) if lines else ''

    def _fetch_products_with_prices(self, recent_norm):
        """Search products matching the conversation and return with client prices + stock."""
        # Extract which product families appear in the conversation
        family_map = {
            'panneau':   ['panneau', 'panneaux', 'panel', 'photovoltaique', 'kwc', 'watt', 'wc',
                          'jinko', 'canadian', 'trina', 'longi', 'blayk', 'pano'],
            'onduleur':  ['onduleur', 'onduleurs', 'inverter', 'huawei', 'deye', 'sungrow',
                          'solax', 'solplanet', 'must', 'fachi', 'fishi'],
            'variateur': ['variateur', 'variateurs', 'vfd', 'pompage', 'puits', 'irrigation',
                          'مضخة', 'محول'],
            'batterie':  ['batterie', 'batteries', 'battery', 'lithium', 'lifepo', 'gel',
                          'stockage', 'pylontech', 'dyness', 'baak', 'kbach'],
            'pompe':     ['pompe', 'pompes', 'pump', 'submersible'],
            'cable':     ['cable', 'câble', 'cables', 'mc4', 'ro2v', 'rvk', 'connecteur'],
            'structure': ['structure', 'structures', 'fixation', 'support', 'montage'],
            'kit':       ['kit', 'kits', 'pack', 'complet'],
        }
        matched_families = [
            family for family, terms in family_map.items()
            if any(term in recent_norm for term in terms)
        ]

        # Build search domain — include family key + top ASCII alternative terms
        if matched_families:
            or_clauses = []
            for family in matched_families[:3]:
                terms = [family] + [
                    t for t in family_map[family]
                    if t.isascii() and len(t) > 3
                ][:3]
                for term in terms:
                    or_clauses.append(('name', 'ilike', term))

            base = [('sale_ok', '=', True), ('active', '=', True)]
            n = len(or_clauses)
            domain = base + (['|'] * (n - 1)) + or_clauses
            products = self.env['product.template'].sudo().search(domain, limit=20)

            # Fallback: if no specific match, return general catalog so AI can still help
            if not products:
                products = self.env['product.template'].sudo().search(
                    [('sale_ok', '=', True), ('active', '=', True)],
                    order='categ_id asc', limit=15,
                )
        else:
            # No specific product mentioned — return full catalog (condensed)
            products = self.env['product.template'].sudo().search(
                [('sale_ok', '=', True), ('active', '=', True)],
                order='categ_id asc', limit=25,
            )

        if not products:
            return ''

        lines = ['CATALOGUE PRODUITS :']
        for p in products:
            try:
                qty = int(p.qty_available)
            except Exception:
                qty = 0
            dispo = 'En stock' if qty > 0 else 'Sur commande'
            desc = ''
            if p.description_sale:
                desc = ' — ' + p.description_sale.strip().replace('\n', ' ')[:60]
            lines.append(
                '- %s | Prix sur demande | %s%s' % (p.name, dispo, desc)
            )
        return '\n'.join(lines)

    def _build_hours_block(self):
        """Return business hours context with current open/closed status."""
        now = datetime.now(_TZ_MOROCCO)
        frac = now.hour + now.minute / 60.0
        wd = now.weekday()
        if wd < 5:
            open_now = 8.5 <= frac < 18.0
        elif wd == 5:
            open_now = 8.5 <= frac < 13.0
        else:
            open_now = False
        status = 'OUVERT' if open_now else 'FERMÉ'
        return 'HORAIRES (%s) : Lun-Ven 08:30-18:00 | Sam 08:30-13:00 | Dim fermé' % status

    def _save_client_info(self, channel, result):
        """Write client_name / client_city from AI response to the partner record."""
        client_name = (result.get('client_name') or '').strip()
        client_city = (result.get('client_city') or '').strip()
        if not client_name and not client_city:
            return
        try:
            partner = self._channel_partner(channel)
            if not partner:
                return
            # Never overwrite an internal user's partner — only update external contacts
            if self.env['res.users'].sudo().search(
                [('partner_id', '=', partner.id), ('share', '=', False)], limit=1
            ):
                _logger.warning(
                    'WhatsappAIBot: _save_client_info blocked — partner %s (%s) is an internal user',
                    partner.id, partner.name,
                )
                return
            vals = {}
            if client_name and (
                not self._is_real_partner_name(partner.name) or partner.name != client_name
            ):
                vals['name'] = client_name
            if client_city and client_city != (getattr(partner, 'city', None) or ''):
                vals['city'] = client_city
            if vals:
                partner.sudo().write(vals)
                _logger.info('WhatsappAIBot: partner %s updated: %s', partner.id, vals)
        except Exception:
            _logger.warning('WhatsappAIBot: failed to save client info', exc_info=True)

    # ------------------------------------------------------------------
    # OpenAI API
    # ------------------------------------------------------------------

    def _call_openai(self, messages, config, context_block=''):
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
            _logger.error('WhatsappAIBot: OpenAI HTTP %s — %s', exc.code, body[:500])
        except urllib.error.URLError as exc:
            _logger.error('WhatsappAIBot: OpenAI network error — %s', exc.reason)
        return None

    @staticmethod
    def _parse_json_response(text):
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        block = re.search(r'\{[^{}]*"escalade"[^{}]*\}', text, re.DOTALL)
        if block:
            text = block.group(0)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            _logger.error('WhatsappAIBot: Cannot parse AI response: %s', text[:400])
            return None

    # ------------------------------------------------------------------
    # Reply posting
    # ------------------------------------------------------------------

    def _post_whatsapp_reply(self, channel, reply, is_escalation=False):
        """Send bot reply as plain text. After escalation, add a Recommencer button."""
        try:
            self._log_outbound_for_history(channel, reply)
            if is_escalation:
                self._send_plain_with_restart(channel, reply)
            else:
                self._send_pure_text(channel, reply)
        except Exception:
            _logger.exception('WhatsappAIBot: Failed to post WhatsApp reply.')

    def _log_outbound_for_history(self, channel, body):
        """Create mail.message + whatsapp.message records for AI context tracking."""
        from markupsafe import Markup, escape
        # Use whatsapp_message type so the chatter orders bot replies AFTER the user message.
        # Create mail.message directly to bypass discuss.channel.message_post(), which would
        # auto-create an outbound whatsapp.message and call _send_message() (double-send).
        html_body = Markup('<p>%s</p>') % escape(body).replace('\n', Markup('<br/>'))
        mail_msg = self.env['mail.message'].sudo().create({
            'body': html_body,
            'model': 'discuss.channel',
            'res_id': channel.id,
            'message_type': 'whatsapp_message',
            'subtype_id': self.env.ref('mail.mt_comment').id,
            'author_id': self.env.ref('base.partner_root').id,
        })
        if mail_msg:
            self.env['whatsapp.message'].sudo().create({
                'mail_message_id': mail_msg.id,
                'mobile_number': '+' + str(getattr(channel, 'whatsapp_number', '') or ''),
                'message_type': 'outbound',
                'wa_account_id': channel.wa_account_id.id if channel.wa_account_id else False,
                'state': 'sent',
            })

    def _send_plain_with_restart(self, channel, reply):
        """Send text with a single ↩ Recommencer button (used after escalation closing)."""
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return
        body_text = reply[:1024] if len(reply) <= 1024 else reply[:1021] + '…'
        payload = json.dumps({
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': number,
            'type': 'interactive',
            'interactive': {
                'type': 'button',
                'body': {'text': body_text},
                'action': {'buttons': [{'type': 'reply', 'reply': {'id': '0', 'title': 'Recommencer'}}]},
            },
        }).encode('utf-8')
        self._wa_post(account, payload)

    def _send_pure_text(self, channel, reply):
        """Send plain WhatsApp text message."""
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return
        payload = json.dumps({
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': number,
            'type': 'text',
            'text': {'body': reply[:4096]},
        }).encode('utf-8')
        self._wa_post(account, payload)

    def _wa_post(self, account, payload):
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

    # ------------------------------------------------------------------
    # Round-robin salesman
    # ------------------------------------------------------------------

    def _get_next_salesman(self, config):
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
        partner = getattr(channel, 'whatsapp_partner_id', False)
        if not partner:
            bot_id = self.env.ref('base.partner_root').id
            internal_partner_ids = set(
                self.env['res.users'].sudo().search([('share', '=', False)])
                .mapped('partner_id.id')
            )
            members = channel.channel_member_ids.filtered(
                lambda m: m.partner_id
                and m.partner_id.id != bot_id
                and m.partner_id.id not in internal_partner_ids
            )
            partner = members[:1].partner_id or False
        return partner

    def _find_existing_lead(self, partner):
        if not partner:
            return False
        lead = self.env['crm.lead'].sudo().search(
            [('partner_id', '=', partner.id), ('active', '=', True)],
            order='create_date desc', limit=1,
        )
        if not lead:
            phone = partner.phone or getattr(partner, 'mobile', None)
            if phone:
                lead = self.env['crm.lead'].sudo().search(
                    [('phone', '=', phone), ('active', '=', True)],
                    order='create_date desc', limit=1,
                )
        return lead or False

    def _get_or_create_lead(self, partner, msg, salesman, service='unknown'):
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
                'description': 'Lead généré automatiquement depuis WhatsApp par l\'assistant AI TECAS.',
            })
        return lead

    def _build_conversation_html(self, messages):
        lines = []
        for m in messages[-10:]:
            label = 'Client' if m['role'] == 'user' else 'TECAS AI'
            content = m['content'].replace('\n', '<br/>')
            lines.append('<b>%s :</b> %s' % (label, content))
        return '<br/><br/>'.join(lines) if lines else '(aucun historique)'

    def _post_lead_briefing(self, lead, salesman, partner, msg, raison, messages):
        phone = (partner.phone or partner.mobile or msg.mobile_number or 'N/A') if partner else (msg.mobile_number or 'N/A')
        convo_html = self._build_conversation_html(messages)
        body = (
            '<p><b>Escalade WhatsApp AI — Action requise</b></p>'
            '<table style="border-collapse:collapse;margin-bottom:8px">'
            '<tr><td style="padding:2px 8px 2px 0"><b>Contact</b></td><td>%s</td></tr>'
            '<tr><td style="padding:2px 8px 2px 0"><b>Téléphone</b></td><td>%s</td></tr>'
            '<tr><td style="padding:2px 8px 2px 0"><b>Raison</b></td><td>%s</td></tr>'
            '</table>'
            '<p><b>Historique :</b></p>'
            '<div style="background:#f5f5f5;padding:10px 14px;border-left:4px solid #00a09d;'
            'font-size:13px;line-height:1.6">%s</div>'
            '<p style="margin-top:10px">Veuillez contacter ce prospect rapidement.</p>'
        ) % (partner.name if partner else 'Inconnu', phone, raison, convo_html)
        lead.sudo().message_post(
            body=Markup(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=[salesman.partner_id.id],
        )

    def _notify_salesman_inbox(self, salesman, msg, raison, messages):
        convo_html = self._build_conversation_html(messages)
        body = (
            '<p><b>Escalade WhatsApp AI — Aucun lead CRM</b></p>'
            '<p><b>Téléphone :</b> %s</p>'
            '<p><b>Raison :</b> %s</p>'
            '<p><b>Historique :</b></p>'
            '<div style="background:#f5f5f5;padding:10px 14px;border-left:4px solid #00a09d;'
            'font-size:13px;line-height:1.6">%s</div>'
        ) % (msg.mobile_number or 'N/A', raison, convo_html)
        salesman.sudo().partner_id.message_post(
            body=Markup(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    # ------------------------------------------------------------------
    # Follow-up nudge (cron)
    # ------------------------------------------------------------------

    @api.model
    def send_followup_nudges(self):
        """Cron entry: scan all active WA channels and nudge stalled ones."""
        config = self.env['whatsapp.ai.bot.config'].sudo().get_singleton()
        if not config.active or not config.wa_account_ids:
            return

        now = datetime.now(timezone.utc)
        since = (now - timedelta(hours=_NUDGE_LOOKBACK_HOURS)).replace(tzinfo=None)

        recent_msgs = self.env['whatsapp.message'].sudo().search([
            ('wa_account_id', 'in', config.wa_account_ids.ids),
            ('mail_message_id.model', '=', 'discuss.channel'),
            ('create_date', '>=', since),
        ])

        channel_ids = {
            msg.mail_message_id.res_id
            for msg in recent_msgs
            if msg.mail_message_id.res_id
        }

        for channel_id in channel_ids:
            try:
                channel = self.env['discuss.channel'].browse(channel_id)
                if channel.exists():
                    self._maybe_nudge_channel(channel, config, now)
            except Exception:
                _logger.warning('WhatsappAIBot: nudge check failed for channel %s', channel_id, exc_info=True)

    def _maybe_nudge_channel(self, channel, config, now):
        """Send one follow-up nudge if the conversation is stalled mid-flow."""
        if self._human_has_taken_over(channel, config):
            return

        wa_msgs = self.env['whatsapp.message'].sudo().search([
            ('mail_message_id.model', '=', 'discuss.channel'),
            ('mail_message_id.res_id', '=', channel.id),
            ('wa_account_id', 'in', config.wa_account_ids.ids),
        ], order='id desc', limit=5)

        if not wa_msgs:
            return

        latest = wa_msgs[0]
        if latest.message_type != 'outbound':
            return

        if not latest.create_date:
            return
        age = now - latest.create_date.replace(tzinfo=timezone.utc)

        # Count consecutive outbound messages from the most recent (no inbound between).
        # 1 = only the bot's real reply, no recall yet → stage 1 (fire at 4h).
        # 2 = first recall already sent → stage 2 (fire 20h after it, ≈24h total).
        # 3+ = both recalls sent → stop.
        consecutive_outbound = 0
        for m in wa_msgs:
            if m.message_type == 'outbound':
                consecutive_outbound += 1
            else:
                break

        if consecutive_outbound == 1:
            delay = timedelta(hours=_NUDGE_1_DELAY_HOURS)
            messages_set = _NUDGE_MESSAGES_1
        elif consecutive_outbound == 2:
            delay = timedelta(hours=_NUDGE_2_DELAY_HOURS)
            messages_set = _NUDGE_MESSAGES_2
        else:
            return

        if age < delay:
            return

        if not any(m.message_type == 'inbound' for m in wa_msgs):
            return

        messages = self._build_messages(channel)
        if not messages:
            return

        if self._was_escalation_closing(messages):
            return

        # Use current session only for language detection
        session_msgs = self._get_current_session_messages(messages)
        lang = self._detect_active_language(session_msgs)
        nudge = messages_set.get(lang or 'fr', messages_set['fr'])

        self._log_outbound_for_history(channel, nudge)
        self._send_pure_text(channel, nudge)
        _logger.info(
            'WhatsappAIBot: recall #%d sent for channel %s (lang=%s)',
            consecutive_outbound, channel.id, lang or 'fr',
        )
