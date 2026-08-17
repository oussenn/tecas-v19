from odoo import models
from odoo.http import request


def prices_are_hidden(env=None):
    """True when the visitor may not see prices: a public (not logged in) user
    browsing the site.

    Deliberately narrow. It answers False without a request — so the backend,
    reports, crons and the API are untouched — and False for any authenticated
    user, portal customers included.

    The question is asked of `request.env.user`, never of the recordset's own
    env: the shop controller searches products in sudo, so a tile's env belongs
    to the superuser and would report "not public" for every visitor. That is
    exactly what left an "Ajouter au panier" button under a hidden price.
    """
    if not request or not getattr(request, 'is_frontend', False):
        return False
    return request.env.user._is_public()


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_combination_info(self, *args, **kwargs):
        """Reuse core's "no price for sale" path to hide prices from visitors.

        v19 already knows how to render a product whose price must not be
        shown: `prevent_zero_price_sale` in combination_info hides the price,
        the quantity input and the add-to-cart button, and reveals the
        #product_unavailable slot — which views/shop_prices_login.xml fills
        with the sign-in box. Setting the same flag for public users therefore
        hides prices everywhere it is honoured, the search autocomplete
        included (see _search_render_results_prices), without duplicating a
        single template.

        What it deliberately does NOT touch is `_is_add_to_cart_possible`:
        core drops the whole product form when that is False, and the form is
        where the variant selectors live. The client wants the configurator to
        stay visible, only the prices to go.
        """
        combination_info = super()._get_combination_info(*args, **kwargs)
        if prices_are_hidden():
            combination_info['prevent_zero_price_sale'] = True
        return combination_info

    def _website_show_quick_add(self):
        """No add-to-cart on a tile whose price is hidden.

        The tile's quick-add reads the website's own zero-price setting rather
        than combination_info, so it survives the override above and would
        leave a cart button next to a price that is not there.
        """
        if prices_are_hidden():
            return False
        return super()._website_show_quick_add()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _website_show_quick_add(self):
        """The shop grid asks the VARIANT, not the template.

        website_sale defines this method on both models and the tile loop
        passes a product.product, so overriding the template alone left an
        "Ajouter au panier" button sitting under a hidden price — proven by
        logging: the template override was never called during a /shop render.
        """
        if prices_are_hidden():
            return False
        return super()._website_show_quick_add()
