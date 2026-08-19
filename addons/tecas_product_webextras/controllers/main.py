from odoo import http
from odoo.http import request

from odoo.addons.website_sale.controllers.main import TableCompute, WebsiteSale


class WebsiteSaleVariants(WebsiteSale):

    @http.route()
    def product(self, product, category=None, pricelist=None, **kwargs):
        """Send a retired product's page to the family that replaced it.

        An archived product still answers on its old URL: the record rule only
        asks whether it is published, and archiving does not unpublish. So the
        page rendered — with no variant behind it, no price, and nothing to
        buy — and that is what Google was serving as the first result for
        "panneau solaire jinko 590w prix maroc".

        A 301 rather than a 404 because the page has earned its ranking: it
        keeps the visitor, and it tells Google the page moved instead of
        letting it drop. Unpublishing these products would look tidier and
        would do the opposite — the record would stop being readable, this
        controller would never run, and every one of those links would end in
        a 404.

        Only archived products are diverted. A live product with no variant
        renders as it always did.
        """
        if not product.sudo().active:
            return request.redirect(product.sudo()._webx_replacement_url(), code=301)
        return super().product(product, category=category, pricelist=pricelist, **kwargs)

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
        self._tecas_split_variants(qcontext, page, order=post.get('order'))
        return response

    def _tecas_split_variants(self, qcontext, page, order=None):
        website = request.website
        ppg = qcontext['ppg']
        ppr = qcontext['ppr']

        variants = self._tecas_expand_to_variants(qcontext['search_product'])
        free_qty_by_id = self._tecas_free_qty_by_id(variants)
        if self._tecas_is_default_order(order):
            # Default view: sellable stock first, "rupture de stock" at the end.
            # An explicit sort from the visitor always wins.
            variants = self._tecas_in_stock_first(variants, free_qty_by_id)

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
            'tecas_out_of_stock_ids': self._tecas_out_of_stock_ids(page_variants, free_qty_by_id),
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

    def _tecas_is_default_order(self, order):
        """Is the visitor actually expressing a sort preference?

        "Featured" and the website's configured default are what the shop lands
        on by itself, so they read as "no choice made" and stock-first still
        applies. Picking name, price or newest is a real choice and wins.
        """
        if not order:
            return True
        order = order.strip()
        return order in ('website_sequence asc', request.website.shop_default_sort)

    def _tecas_free_qty_by_id(self, variants):
        """Free-to-sell quantity per variant, in one grouped query.

        Reading `free_qty` record by record would also pull incoming/outgoing moves
        for every variant on the page; the shop only needs on-hand minus reserved,
        and it needs it for the whole result set to be able to sort by it.
        """
        if not variants:
            return {}
        company = request.website.company_id
        groups = request.env['stock.quant'].sudo()._read_group(
            [
                ('product_id', 'in', variants.ids),
                ('location_id.usage', '=', 'internal'),
                ('company_id', 'in', (company.id, False)),
            ],
            groupby=['product_id'],
            aggregates=['quantity:sum', 'reserved_quantity:sum'],
        )
        return {
            product.id: quantity - reserved
            for product, quantity, reserved in groups
        }

    def _tecas_in_stock_first(self, variants, free_qty_by_id):
        """Stable partition: everything sellable first, out of stock last."""
        in_stock, out_of_stock = [], []
        for variant in variants:
            bucket = out_of_stock if self._tecas_is_out_of_stock(variant, free_qty_by_id) else in_stock
            bucket.append(variant.id)
        return request.env['product.product'].with_context(bin_size=True).browse(in_stock + out_of_stock)

    def _tecas_is_out_of_stock(self, variant, free_qty_by_id):
        # Services and non-tracked goods are always orderable, never dimmed.
        if not variant.is_storable:
            return False
        return free_qty_by_id.get(variant.id, 0) <= 0

    def _tecas_out_of_stock_ids(self, variants, free_qty_by_id):
        """Variants to dim: storable, tracked, and nothing free to sell."""
        return {
            variant.id for variant in variants
            if self._tecas_is_out_of_stock(variant, free_qty_by_id)
        }
