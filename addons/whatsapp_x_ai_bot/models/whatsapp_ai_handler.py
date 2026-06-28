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

_NUDGE_MESSAGES = {
    'fr':      "Êtes-vous toujours là ? 😊\nN'hésitez pas à continuer, je suis là pour vous aider !",
    'anglais': "Are you still there? 😊\nFeel free to continue — I'm here to help!",
    'arabe':   "هل لا تزال هناك؟ 😊\nلا تتردد في المتابعة، أنا هنا للمساعدة!",
}

_NUDGE_SILENCE_MIN = 1
_NUDGE_GIVE_UP_MIN = 30

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
        """Detect active language from current-session bot messages only.

        Returns 'anglais' or 'arabe'; None means French/Darija-French (no injection needed).
        Call with _get_current_session_messages() result, never the full history.
        """
        bot_msgs = [m['content'] for m in session_messages if m['role'] == 'assistant']
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
            'hello', 'welcome', 'solar', 'panel', 'inverter', 'battery',
            'please', 'thank', 'installation', 'quote', 'price',
            'how ', 'what ', 'when ', 'where ', 'would ',
        ]
        hits = sum(1 for w in english_markers if w in combined.lower())
        if hits >= 3:
            return 'anglais'
        return None

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
            if not msg_body:
                _logger.info('WhatsappAIBot: voice/media on channel %s — sending French welcome', channel.id)
                self._post_whatsapp_reply(channel, self._VOICE_FALLBACK_FR)
                return

            if not config.openai_api_key:
                _logger.error('WhatsappAIBot: OpenAI API key not set')
                return

            messages = self._build_messages(channel)
            if not messages:
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
                    'Repondre avec bienvenue + menu principal uniquement. '
                    'Utiliser SALUTATION_NOM si present. '
                    'Respecter LANGUE ACTIVE.'
                )

            result = self._call_openai(messages, config, context_block)
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
        if not config.wa_account_id:
            _logger.warning('WhatsappAIBot: No WhatsApp account selected in Bot configuration')
            return False
        return msg.wa_account_id.id == config.wa_account_id.id

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
        """Return the last 20 messages as an OpenAI-compatible list."""
        wa_msgs = self.env['whatsapp.message'].search(
            [
                ('mail_message_id.model', '=', 'discuss.channel'),
                ('mail_message_id.res_id', '=', channel.id),
            ],
            order='id desc',
            limit=20,
        )
        wa_msgs = wa_msgs.sorted('id')
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

    def _build_context_block(self, channel, messages, session_msgs, lang):
        """Build a context string injected into the system prompt for this request."""
        recent = ' '.join(m['content'] for m in messages[-3:]).lower()
        recent_norm = (
            recent
            .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
            .replace('à', 'a').replace('â', 'a')
            .replace('ô', 'o').replace('û', 'u').replace('î', 'i')
            .replace('ç', 'c')
        )

        blocks_priority = []
        blocks_optional = []

        # 0. Language lock — from current session, prevents reversion on short inputs
        if lang:
            blocks_priority.append((
                'lang',
                'LANGUE ACTIVE : %s\n'
                'REGLE ABSOLUE : Utiliser uniquement cette langue pour toute la reponse, '
                'y compris les champs "reponse" et "raison" du JSON. '
                'Ne jamais revenir au francais.' % lang,
            ))

        # 1. Client profile — phone always; name/city with targeted scope
        try:
            partner = self._channel_partner(channel)
            if partner:
                phone = partner.phone or getattr(partner, 'mobile', None)
                profile_lines = ['PROFIL CLIENT :']

                if phone:
                    profile_lines.append('- TEL : %s (connu, ne pas redemander)' % phone)

                if self._is_real_partner_name(partner.name):
                    # On session start: inject for greeting only
                    session_user_count = sum(1 for m in session_msgs if m['role'] == 'user')
                    if session_user_count <= 1:
                        profile_lines.append('- SALUTATION_NOM : %s' % partner.name)
                    else:
                        # Mid-flow: only for the name confirmation step
                        profile_lines.append('- NOM_CONNU : %s' % partner.name)

                city = getattr(partner, 'city', None)
                if city:
                    profile_lines.append('- VILLE_CONNUE : %s' % city)

                if len(profile_lines) > 1:
                    blocks_priority.append(('profile', '\n'.join(profile_lines)))
        except Exception:
            _logger.warning('WhatsappAIBot: context — customer profile query failed')

        # 2. Product catalog (optional, keyword-triggered)
        if _PRODUCT_KEYWORDS & set(recent_norm.split()):
            try:
                products = self.env['product.template'].sudo().search(
                    [('sale_ok', '=', True), ('active', '=', True)],
                    order='categ_id asc', limit=20,
                )
                if products:
                    lines = ['CATALOGUE PRODUITS :']
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

        # 3. Promotions (optional, keyword-triggered)
        if _PROMO_KEYWORDS & set(recent_norm.split()):
            try:
                promos = self.env['product.template'].sudo().search(
                    [('sale_ok', '=', True), ('active', '=', True),
                     ('description_sale', 'ilike', 'promo')],
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

        # 4. Business hours (optional, keyword-triggered)
        if _HOURS_KEYWORDS & set(recent_norm.split()):
            try:
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
                blocks_priority.append(('hours', '\n'.join([
                    "HORAIRES (%s) : Lun-Ven 08:30-18:00 | Sam 08:30-13:00 | Dim fermé" % status,
                ])))
            except Exception:
                _logger.warning('WhatsappAIBot: context — business hours failed')

        if not blocks_priority and not blocks_optional:
            return ''

        CHAR_BUDGET = 1600
        parts = [text for _k, text in blocks_priority]
        chars_used = sum(len(p) for p in parts)

        for key, text in blocks_optional:
            remaining = CHAR_BUDGET - chars_used
            if remaining <= 0:
                break
            if len(text) <= remaining:
                parts.append(text)
                chars_used += len(text)
            elif key == 'products':
                lines = text.split('\n')
                kept = [lines[0]]
                for line in lines[1:]:
                    if chars_used + len('\n'.join(kept)) + len(line) + 1 <= CHAR_BUDGET:
                        kept.append(line)
                    else:
                        kept.append('(liste tronquée)')
                        break
                truncated = '\n'.join(kept)
                parts.append(truncated)
                chars_used += len(truncated)

        return '\n\n---\nCONTEXTE TEMPS RÉEL :\n' + '\n\n'.join(parts) if parts else ''

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
        """Route reply to correct WhatsApp message type."""
        msg_class = self._classify_reply(reply)
        try:
            if msg_class == 'profile':
                header, items = self._split_header_and_list(reply)
                self._log_outbound_for_history(channel, reply)
                self._send_interactive_profile(channel, header, items)
            elif msg_class == 'client_menu':
                header, items = self._split_header_and_list(reply)
                self._log_outbound_for_history(channel, reply)
                self._send_buttons_chunked(channel, header, items)
            else:
                self._log_outbound_for_history(channel, reply)
                if is_escalation:
                    self._send_plain_with_restart(channel, reply)
                else:
                    self._send_pure_text(channel, reply)
        except Exception:
            _logger.exception('WhatsappAIBot: Failed to post WhatsApp reply.')

    def _classify_reply(self, reply):
        """2-3 items → buttons; 4+ items → chunked buttons; else → plain text."""
        _, items = self._split_header_and_list(reply)
        n = len(items)
        if 2 <= n <= 3:
            return 'profile'
        if n >= 4:
            return 'client_menu'
        return 'plain'

    @staticmethod
    def _split_header_and_list(reply):
        """Extract (header, [(id, title), ...]) from a numbered-list reply."""
        _inline_re = re.compile(r'([1-9][0-9]?)[\.。)]\s+(.+?)(?=\s+[1-9][0-9]?[\.。)]|\s*$)')

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

        if items and items[0][0] != '1' and header_lines:
            last = header_lines[-1]
            m2 = re.search(r':\s*(1[\.。)]\s*(.+))$', last)
            if m2:
                option_text = re.split(r'\s+\d', m2.group(2))[0].strip()
                items.insert(0, ('1', option_text))
                header_lines[-1] = last[:m2.start()].rstrip(':').strip()
                if not header_lines[-1]:
                    header_lines.pop()

        return '\n'.join(header_lines).strip(), items

    @staticmethod
    def _clean_label(text, max_len):
        """Truncate to max_len, preferring word boundaries when they keep ≥75% of space."""
        clean = re.split(r'\s*[\(（/]', text)[0].strip() or text.strip()
        if len(clean) <= max_len:
            return clean
        truncated = clean[:max_len].rsplit(' ', 1)[0]
        return truncated if len(truncated) >= (max_len * 3 // 4) else clean[:max_len]

    def _log_outbound_for_history(self, channel, body):
        """Create mail.message + whatsapp.message records for AI context tracking."""
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
        """Send 2-3 option reply as WhatsApp quick-reply buttons."""
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return
        body_text = (header or 'Choisissez une option :')[:1024]
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

    def _send_buttons_chunked(self, channel, header, items):
        """Send 4+ options as consecutive 3-button messages — no 'Voir les options' needed."""
        account = channel.wa_account_id
        if not account or not account.phone_uid:
            return
        number = str(getattr(channel, 'whatsapp_number', '') or '')
        if not number:
            return

        all_items = list(items[:9])
        all_items.append(('0', 'Recommencer'))

        chunks = [all_items[i:i + 3] for i in range(0, len(all_items), 3)]
        for idx, chunk in enumerate(chunks):
            body_text = (header or 'Choisissez une option :')[:1024] if idx == 0 else '•'
            buttons = [
                {'type': 'reply', 'reply': {'id': iid, 'title': self._clean_label(title, 20)}}
                for iid, title in chunk
            ]
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
            members = channel.channel_member_ids.filtered(
                lambda m: m.partner_id and m.partner_id.id != bot_id
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
        if not config.active or not config.wa_account_id:
            return

        now = datetime.now(timezone.utc)
        since = (now - timedelta(minutes=_NUDGE_GIVE_UP_MIN)).replace(tzinfo=None)

        recent_msgs = self.env['whatsapp.message'].sudo().search([
            ('wa_account_id', '=', config.wa_account_id.id),
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
            ('wa_account_id', '=', config.wa_account_id.id),
        ], order='id desc', limit=5)

        if not wa_msgs:
            return

        latest = wa_msgs[0]
        if latest.message_type != 'outbound':
            return

        if not latest.create_date:
            return
        age = now - latest.create_date.replace(tzinfo=timezone.utc)
        if age < timedelta(minutes=_NUDGE_SILENCE_MIN) or age > timedelta(minutes=_NUDGE_GIVE_UP_MIN):
            return

        # Already nudged if two consecutive outbound messages with no inbound between
        consecutive_outbound = 0
        for m in wa_msgs:
            if m.message_type == 'outbound':
                consecutive_outbound += 1
            else:
                break
        if consecutive_outbound >= 2:
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
        nudge = _NUDGE_MESSAGES.get(lang or 'fr', _NUDGE_MESSAGES['fr'])

        self._log_outbound_for_history(channel, nudge)
        self._send_pure_text(channel, nudge)
        _logger.info('WhatsappAIBot: nudge sent for channel %s (lang=%s)', channel.id, lang or 'fr')
