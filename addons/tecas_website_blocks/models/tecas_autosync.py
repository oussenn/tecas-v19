import hashlib
import logging

from lxml import etree

from odoo import api, models

_logger = logging.getLogger(__name__)

# Blocks that re-render themselves from live data: {section class: template}.
# A dropped copy keeps its markup frozen until one of these runs, which is why
# every block listed here must also carry data-tecas-auto="1" in its template.
AUTO_BLOCKS = {
    's_tecas_categories': 'tecas_website_blocks.s_tecas_categories',
    's_tecas_news': 'tecas_website_blocks.s_tecas_news',
}
PRODUCTS_MENU_TEMPLATE = 'tecas_website_blocks.s_tecas_products_menu'
AUTO_FLAG = 'data-tecas-auto'
# Fingerprint of the html this module last wrote into a block. It is what tells
# an untouched block from one the client has edited: see _signature().
AUTO_SIG = 'data-tecas-sig'
# Prefix on that fingerprint, so the way it is computed can change without
# every existing block reading as hand-edited: a stamp that does not carry the
# current prefix is treated as unstamped, adopted and stamped afresh.
SIG_VERSION = 'v2'
# arch_db is a translated column, and Odoo re-derives the other languages from
# this one. The fingerprint is therefore only meaningful against the source:
# read in fr_FR the same block hashes differently, which had the guard
# reporting every block as hand-edited on a French site.
SOURCE_LANG = 'en_US'
PRODUCTS_MENU_URL = '/shop'
PRODUCTS_MENU_PARAM = 'tecas.products_menu_id'
SHOP_LABEL = 'Toute la boutique'
# Odoo's own "narrow" mega-menu width: the panel lines up with the page
# container instead of spanning the full window.
MEGA_MENU_CLASSES = 'o_mega_menu_container_size'

# A page arch must never contain QWeb: ir_ui_view.distribute_branding() strips a
# node's editor branding as soon as a descendant carries a t-* attribute, which
# costs #wrap its data-oe-model and leaves the builder with no drop zone at all
# (see the comment in views/snippets/s_tecas_categories.xml). So the category
# tiles are stored as plain html and this module re-renders them whenever the
# data behind them moves — same result as a live block, without breaking the
# page editor.


def _installed_langs(env):
    """Codes of the languages actually installed on the site.

    active_test is forced back on: this runs from whatever context triggered
    the write, and a caller that searched with active_test=False (a data
    script, an import) would otherwise hand back all ~80 res.lang rows. Odoo
    then refuses the first uninstalled one with "Invalid language code" and the
    whole refresh is lost.
    """
    codes = env['res.lang'].sudo().with_context(active_test=True).search([]).mapped('code')
    return codes or ['en_US']


def _has_published_product(env, categ):
    """True when something a visitor may buy sits under this category."""
    return bool(env['product.template'].sudo().search_count(
        [('public_categ_ids', 'child_of', categ.id), ('is_published', '=', True)], limit=1))


def _is_browsable(env, categ):
    """True when a visitor can open this category's page.

    Two ways in: something published sits underneath it, or it carries the
    tecas_show_when_empty flag. tecas_hide_from_website closes both — see
    product_public_category._search_has_published_products, which applies the
    same two flags to the shop itself.
    """
    if categ.tecas_hide_from_website:
        return False
    if categ.tecas_show_when_empty:
        return True
    return _has_published_product(env, categ)


def _relevant_categories(env):
    """Top-level public categories a visitor can actually browse.

    Whether a family is worth a homepage TILE is a stricter question, and the
    caller asks it: see _tecas_homepage_tiles. Everything a visitor may open
    belongs in the menu.
    """
    return env['product.public.category'].sudo().search(
        [('parent_id', '=', False)], order='sequence, name'
    ).filtered(lambda c: _is_browsable(env, c))


def _signature(node):
    """Fingerprint of what a section SAYS, not of how it is written down.

    Hashing the serialised xml was too brittle to be useful: an arch that is
    parsed and written back — by Odoo's own view handling, or by a script that
    reorders the blocks on a page — comes back with the same content spelled
    differently, and the block then read as hand-edited and froze for good. It
    is a safe failure, in that nothing is destroyed, but it quietly turns off
    the self-updating that these blocks exist for.

    So the hash covers the tags, their attributes sorted, and the text with its
    whitespace collapsed. Reformatting cannot move it; changing a word, an
    image or a link still does, which is the whole point.
    """
    clone = etree.fromstring(etree.tostring(node))
    clone.attrib.pop(AUTO_SIG, None)
    parts = []
    for element in clone.iter():
        # Comments and processing instructions carry a callable as their tag,
        # and its repr holds a memory address — different in every process, so
        # a block with a comment in it would never match its own stamp again.
        if not isinstance(element.tag, str):
            continue
        parts.append(element.tag)
        parts.extend('%s=%s' % pair for pair in sorted(element.attrib.items()))
        text = ' '.join((element.text or '').split())
        if text:
            parts.append(text)
    digest = hashlib.sha1('\x00'.join(parts).encode('utf-8')).hexdigest()[:16]
    return '%s:%s' % (SIG_VERSION, digest)


def _refresh_auto_blocks(env):
    """Re-render every self-updating block into the PAGES that opted in.

    Restricted to views backing a website.page on purpose. Searching all qweb
    views also matches this module's own snippet templates, and rewriting one
    replaces its t-foreach with frozen html — which silently kills the block's
    dynamism for every future drop. Only pages are ever rewritten.

    A block is only replaced while it still matches what this module last wrote
    into it. The section carries the fingerprint of that html; if the section on
    the page no longer hashes to it, somebody has edited the block by hand and
    it is left alone for good. Without that check every restart quietly threw
    away whatever the client had changed inside these sections — a swapped
    photo, a reworded title — which is exactly what was happening: the
    data-tecas-auto marker survives an in-place edit in the website editor, so
    it could never have detected one.
    """
    page_view_ids = env['website.page'].sudo().search([]).view_id.ids
    if not page_view_ids:
        return 0

    sources = {}
    for section_class, template in AUTO_BLOCKS.items():
        rendered = env['ir.qweb'].sudo()._render(template)
        source = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8')).find('section')
        if source is None:
            _logger.warning('tecas: %s rendered no <section>, skipping it', template)
            continue
        sources[section_class] = source
    if not sources:
        return 0

    # Read in the source language, always: see SOURCE_LANG.
    views = env['ir.ui.view'].sudo().with_context(lang=SOURCE_LANG).search(
        [('id', 'in', page_view_ids)])
    touched = 0
    for view in views:
        arch = view.arch_db
        if AUTO_FLAG not in arch:
            continue                        # hand-edited copy: leave it alone
        root = etree.fromstring(arch.encode('utf-8'))
        replaced = False
        for section_class, source in sources.items():
            targets = root.xpath(
                "//section[contains(@class,'%s')][@%s='1']" % (section_class, AUTO_FLAG))
            for old in targets:
                stamped = old.get(AUTO_SIG) or ''
                # A stamp from an older scheme says nothing about whether the
                # block was edited, so it is re-stamped rather than trusted.
                if stamped.startswith(SIG_VERSION + ':') and stamped != _signature(old):
                    _logger.info(
                        'tecas: %s in view %s was edited by hand, leaving it alone',
                        section_class, view.id)
                    continue
                new = etree.fromstring(etree.tostring(source))
                # Preserve whatever the editor put on the node (data-snippet,
                # data-name, and any class the client added from the builder).
                for attr, value in old.attrib.items():
                    if attr not in ('class', AUTO_SIG):
                        new.set(attr, value)
                # Stamped last, over the finished node, so the hash covers
                # exactly the html that ends up on the page.
                new.set(AUTO_SIG, _signature(new))
                new.tail = old.tail
                old.getparent().replace(old, new)
                replaced = True
        if not replaced:
            continue

        new_arch = etree.tostring(root, encoding='unicode')
        if new_arch != arch:
            for lang in set(_installed_langs(env)) | {SOURCE_LANG}:
                view.with_context(lang=lang).write({'arch_db': new_arch})
            touched += 1

    return touched


def _menu_groups(env):
    """The two levels behind "Nos Produits", as plain values for the template.

    A family is a top-level category, a sub-family one of its children, and
    both are dropped unless a visitor can open them — the menu must never offer
    a category page that 404s. An empty family flagged tecas_show_when_empty
    counts as openable, which is how the pumps are announced ahead of their
    products.
    """
    slug = env['ir.http']._slug

    def browsable(categ):
        return _is_browsable(env, categ)

    groups = []
    for root in _relevant_categories(env):
        children = root.child_id.sorted(lambda c: (c.sequence, c.name or ''))
        groups.append({
            'name': (root.name or '').strip(),
            'url': '/shop/category/%s' % slug(root),
            'children': [{'name': (c.name or '').strip(),
                          'url': '/shop/category/%s' % slug(c)}
                         for c in children if browsable(c)],
        })
    return groups


def _sync_products_menu(env):
    """Keep the products mega menu in step with the categories.

    The menu is named explicitly by the ir.config_parameter
    tecas.products_menu_id, never found by url. Odoo rewrites a menu's url to
    "#" the moment it gains children (or becomes a mega menu), so a url lookup
    works once and then silently matches the wrong records — which is how an
    earlier version of this filled the unused default menu tree with
    duplicates.

    The panel replaces the flat list of child menu items that used to hang off
    "Nos Produits": v19 allows only two levels of website.menu, and a mega menu
    may not have children at all, so the old entries have to go for the
    families-and-sub-families layout to exist. They carry nothing that is not
    regenerated here.
    """
    menu_id = env['ir.config_parameter'].sudo().get_param(PRODUCTS_MENU_PARAM)
    if not menu_id:
        return 0
    menu = env['website.menu'].sudo().browse(int(menu_id)).exists()
    if not menu:
        _logger.warning('tecas: %s points at a menu that no longer exists', PRODUCTS_MENU_PARAM)
        return 0

    # Hand-edited panel: the editor rewrites the section and the marker goes
    # with it. Never overwrite the client's own work.
    if menu.mega_menu_content and AUTO_FLAG not in menu.mega_menu_content:
        return 0

    touched = 0
    if menu.child_id:
        # website.menu._validate_parent_menu() rejects a mega menu that has
        # children, so this has to happen before the content is written.
        menu.child_id.unlink()
        touched += 1

    # One render per language: the panel is mostly markup, but the family names
    # inside it are translatable, and mega_menu_content is a translated field.
    # Writing a single render would stamp one language over all of them.
    for lang in _installed_langs(env):
        env_lang = env(context=dict(env.context, lang=lang))
        content = str(env_lang['ir.qweb']._render(PRODUCTS_MENU_TEMPLATE, {
            'groups': _menu_groups(env_lang),
            'shop_url': PRODUCTS_MENU_URL,
            'shop_label': SHOP_LABEL,
        })).strip()
        menu_lang = menu.with_context(lang=lang)
        if (menu_lang.mega_menu_content or '').strip() != content:
            menu_lang.write({'mega_menu_content': content})
            touched += 1

    if menu.mega_menu_classes != MEGA_MENU_CLASSES:
        menu.write({'mega_menu_classes': MEGA_MENU_CLASSES})
        touched += 1

    return touched


def _run(env):
    """Never let a website refresh break the business write that triggered it."""
    try:
        # This runs from whatever context triggered the write, and that context
        # must not decide what the website shows. A caller searching with
        # active_test=False (a data script, an import) otherwise leaks it here,
        # and archived products still carrying is_published=True then make an
        # empty category look full — it lands in the menu with links that 404,
        # because the shop itself only ever counts active products. Hit twice
        # on prod 2026-08-16 ("Pompes", then "Parafoudre").
        env = env(context=dict(env.context, active_test=True))
        # `child_of` reads parent_path, and a category created in this same
        # transaction has none until the ORM flushes — an empty prefix matches
        # every product, with the same visible result.
        env.flush_all()
        tiles = _refresh_auto_blocks(env)
        menus = _sync_products_menu(env)
        if tiles or menus:
            _logger.info('tecas autosync: %d page(s) refreshed, %d menu change(s)',
                         tiles, menus)
    except Exception:
        _logger.exception('tecas autosync failed; website left as it was')


def _schedule(env):
    """Coalesce a bulk write into a single refresh at the end of the transaction."""
    if env.context.get('tecas_skip_autosync') or env.cr.precommit.data.get('tecas_autosync'):
        return
    env.cr.precommit.data['tecas_autosync'] = True

    def _callback():
        env.cr.precommit.data.pop('tecas_autosync', None)
        _run(env(context=dict(env.context, tecas_skip_autosync=True)))

    env.cr.precommit.add(_callback)


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    # Fields that change what a tile or a menu entry looks like. The
    # show-while-empty flag belongs here too: it is the only thing that decides
    # whether an empty family is in the menu at all.
    _TECAS_WATCHED = {'name', 'sequence', 'parent_id', 'image_1920', 'website_id',
                      'tecas_show_when_empty', 'tecas_hide_from_website'}

    # Marks an image as the script's own work. Set only by
    # scripts/set_category_images.py, via with_context(); any other write to
    # image_1920 clears the flag in write() below, which is what protects a
    # picture the client uploaded by hand.
    _TECAS_AUTO_IMAGE_CTX = 'tecas_auto_image'

    @api.model
    def _tecas_refresh_website(self):
        """Called from views/products_menu.xml on install and on every upgrade.

        Without it a deploy that only changes the panel's markup would leave
        the stored copy untouched until the next time someone edits a
        category — the menu would still be the old one after the upgrade.
        """
        _run(self.env)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _schedule(self.env)
        return records

    def write(self, vals):
        # A picture that arrives from anywhere other than the image script
        # belongs to whoever put it there. Recording that here — rather than
        # trusting the script to know — is what makes the protection hold for
        # an upload through the backend, an import, or the website editor.
        if 'image_1920' in vals and not self.env.context.get(self._TECAS_AUTO_IMAGE_CTX):
            vals = dict(vals, tecas_image_is_auto=False)
        result = super().write(vals)
        if self._TECAS_WATCHED.intersection(vals):
            _schedule(self.env)
        return result

    def unlink(self):
        result = super().unlink()
        _schedule(self.env)
        return result


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # A tile appears or disappears with publication and categorisation, and the
    # first published product supplies the image when the category has none.
    _TECAS_WATCHED = {'is_published', 'website_published', 'public_categ_ids',
                      'active', 'image_1920'}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(self._TECAS_WATCHED.intersection(vals) for vals in vals_list):
            _schedule(self.env)
        return records

    def write(self, vals):
        result = super().write(vals)
        if self._TECAS_WATCHED.intersection(vals):
            _schedule(self.env)
        return result
