import logging

from lxml import etree

from odoo import api, models

_logger = logging.getLogger(__name__)

CATEGORIES_SNIPPET = 'tecas_website_blocks.s_tecas_categories'
AUTO_FLAG = 'data-tecas-auto'
PRODUCTS_MENU_URL = '/shop'
PRODUCTS_MENU_PARAM = 'tecas.products_menu_id'
SHOP_LABEL = 'Toute la boutique'

# A page arch must never contain QWeb: ir_ui_view.distribute_branding() strips a
# node's editor branding as soon as a descendant carries a t-* attribute, which
# costs #wrap its data-oe-model and leaves the builder with no drop zone at all
# (see the comment in views/snippets/s_tecas_categories.xml). So the category
# tiles are stored as plain html and this module re-renders them whenever the
# data behind them moves — same result as a live block, without breaking the
# page editor.


def _relevant_categories(env):
    """Top-level public categories that hold at least one published product.

    Categories with nothing published make /shop/category/<id> return 404, so
    they must not produce a tile or a menu entry.
    """
    categories = env['product.public.category'].sudo().search(
        [('parent_id', '=', False)], order='sequence, name')
    Template = env['product.template'].sudo()
    return categories.filtered(lambda c: Template.search_count(
        [('public_categ_ids', 'child_of', c.id), ('is_published', '=', True)], limit=1))


def _refresh_category_tiles(env):
    """Re-render the tiles into every PAGE that opted in with the auto flag.

    Restricted to views backing a website.page on purpose. Searching all qweb
    views also matches this module's own snippet template, and rewriting that
    replaces its t-foreach with frozen html — which silently kills the block's
    dynamism for every future drop. Only pages are ever rewritten.
    """
    page_view_ids = env['website.page'].sudo().search([]).view_id.ids
    if not page_view_ids:
        return 0
    views = env['ir.ui.view'].sudo().search(
        [('id', 'in', page_view_ids), ('arch_db', 'like', 's_tecas_categories')])
    if not views:
        return 0

    rendered = env['ir.qweb'].sudo()._render(CATEGORIES_SNIPPET)
    source = etree.fromstring(('<root>%s</root>' % rendered).encode('utf-8')).find('section')
    if source is None:
        _logger.warning('tecas: categories snippet rendered no <section>, skipping refresh')
        return 0

    touched = 0
    for view in views:
        arch = view.arch_db
        if AUTO_FLAG not in arch:
            continue                        # hand-edited copy: leave it alone
        root = etree.fromstring(arch.encode('utf-8'))
        targets = root.xpath(
            "//section[contains(@class,'s_tecas_categories')][@%s='1']" % AUTO_FLAG)
        if not targets:
            continue

        for old in targets:
            new = etree.fromstring(etree.tostring(source))
            # Preserve whatever the editor put on the node (data-snippet,
            # data-name, and any class the client added from the builder).
            for attr, value in old.attrib.items():
                if attr != 'class':
                    new.set(attr, value)
            new.tail = old.tail
            old.getparent().replace(old, new)

        new_arch = etree.tostring(root, encoding='unicode')
        if new_arch != arch:
            for lang in {'en_US', env.lang or 'en_US'} | set(
                    env['res.lang'].sudo().search([]).mapped('code')):
                view.with_context(lang=lang).write({'arch_db': new_arch})
            touched += 1

    return touched


def _sync_products_menu(env):
    """Keep the products dropdown in step with the categories.

    The parent is named explicitly by the ir.config_parameter
    tecas.products_menu_id, never found by url. Odoo rewrites a menu's url to
    "#" the moment it gains children, so a url lookup works once and then
    silently matches the wrong records — which is how an earlier version of
    this filled the unused default menu tree with duplicates.
    """
    menu_id = env['ir.config_parameter'].sudo().get_param(PRODUCTS_MENU_PARAM)
    if not menu_id:
        return 0
    parent = env['website.menu'].sudo().browse(int(menu_id)).exists()
    if not parent:
        _logger.warning('tecas: %s points at a menu that no longer exists', PRODUCTS_MENU_PARAM)
        return 0

    Menu = env['website.menu'].sudo()
    slug = env['ir.http']._slug
    wanted = [(c.name.strip(), '/shop/category/%s' % slug(c))
              for c in _relevant_categories(env)]
    wanted.append((SHOP_LABEL, PRODUCTS_MENU_URL))

    # Only entries this module owns are ever rewritten or removed; anything the
    # client adds to the dropdown by hand is left exactly where it is.
    children = Menu.search([('parent_id', '=', parent.id)])
    owned = children.filtered(
        lambda m: m.url and (m.url.startswith('/shop/category/') or m.url == PRODUCTS_MENU_URL))
    by_url = {m.url: m for m in owned}

    touched = 0
    sequence = 10
    for name, url in wanted:
        existing = by_url.pop(url, None)
        if existing:
            if existing.name != name or existing.sequence != sequence:
                existing.write({'name': name, 'sequence': sequence})
                touched += 1
        else:
            Menu.create({
                'name': name,
                'url': url,
                'parent_id': parent.id,
                'sequence': sequence,
                'website_id': parent.website_id.id,
            })
            touched += 1
        sequence += 10

    for stale in by_url.values():
        stale.unlink()
        touched += 1

    return touched


def _run(env):
    """Never let a website refresh break the business write that triggered it."""
    try:
        tiles = _refresh_category_tiles(env)
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

    # Fields that change what a tile or a menu entry looks like.
    _TECAS_WATCHED = {'name', 'sequence', 'parent_id', 'image_1920', 'website_id'}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _schedule(self.env)
        return records

    def write(self, vals):
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
