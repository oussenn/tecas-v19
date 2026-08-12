from odoo import http
from odoo.http import request

from odoo.addons.website_sale.controllers.main import TableCompute, WebsiteSale


class WebsiteSaleVariants(WebsiteSale):

    @http.route()
    def shop(self, page=0, category=None, search='', min_price=0.0, max_price=0.0, tags='', **post):
        """Render one tile per variant instead of one per template.

        The whole standard lookup runs untouched, so the category tree, the price
        slider, the attribute sidebar and the search all keep working on templates.
        Only the paged slice that actually gets rendered is swapped for variants.
        """
        response = super().shop(
            page=page, category=category, search=search,
            min_price=min_price, max_price=max_price, tags=tags, **post
        )
        qcontext = getattr(response, 'qcontext', None)
        if not qcontext or 'search_product' not in qcontext:
            return response  # a redirect, not the shop page
        # Always defined so the templates can be read without guards.
        qcontext.setdefault('tecas_split_variants', False)
        qcontext.setdefault('tecas_out_of_stock_ids', set())
        if not request.website.shop_split_variants:
            return response
        self._tecas_split_variants(qcontext, page)
        return response

    def _tecas_split_variants(self, qcontext, page):
        website = request.website
        ppg = qcontext['ppg']
        ppr = qcontext['ppr']

        variants = self._tecas_expand_to_variants(qcontext['search_product'])

        pager = website.pager(
            url=self._get_shop_path(qcontext.get('category')),
            total=len(variants),
            page=page,
            step=ppg,
            scope=5,
            url_args=self._tecas_pager_url_args(),
        )
        offset = pager['offset']
        page_variants = variants[offset:offset + ppg]
        page_variants.fetch()

        prices = page_variants._get_sales_prices(website)

        qcontext.update({
            'pager': pager,
            'products': page_variants,
            'search_count': len(variants),
            'bins': TableCompute().process(page_variants, ppg, ppr),
            # The tile reads `product_variants[product]`; here the tile *is* the variant.
            'product_variants': {variant: variant for variant in page_variants},
            'get_product_prices': lambda product: prices[product.id],
            'tecas_split_variants': True,
            'tecas_out_of_stock_ids': self._tecas_out_of_stock_ids(page_variants),
        })

        # website_sale_wishlist compares `product in products_in_wishlist`, and that
        # recordset holds templates. Give it variants so the models match.
        if 'products_in_wishlist' in qcontext:
            qcontext['products_in_wishlist'] = request.env['product.wishlist'].current().product_id

    def _tecas_expand_to_variants(self, templates):
        """Flatten templates into their variants, keeping the search order."""
        variant_ids = []
        for template in templates:
            variant_ids.extend(template.product_variant_ids.ids)
        return request.env['product.product'].with_context(bin_size=True).browse(variant_ids)

    def _tecas_pager_url_args(self):
        args = {
            key: value for key, value in request.httprequest.args.items()
            if key != 'page'
        }
        attribute_values = request.httprequest.args.getlist('attribute_values')
        if attribute_values:
            args['attribute_values'] = attribute_values
        return args

    def _tecas_out_of_stock_ids(self, variants):
        """Variants to dim: storable, tracked, and nothing free to sell."""
        out_of_stock = set()
        for variant in variants.sudo():
            if not variant.is_storable:
                continue
            if variant.free_qty <= 0:
                out_of_stock.add(variant.id)
        return out_of_stock
