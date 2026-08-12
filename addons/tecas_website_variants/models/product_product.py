from odoo import fields, models
from odoo.http import request


class ProductProduct(models.Model):
    """Let a variant stand in for a template in the shop grid.

    The shop templates call a handful of `product.template` helpers on whatever
    record sits in a tile. When the grid is filled with variants instead, these
    delegates keep the standard tile markup working unchanged.
    """
    _inherit = 'product.product'

    def _get_ribbon(self, price_vals=None, auto_assign_ribbons=None, variant=None):
        self.ensure_one()
        return self.product_tmpl_id._get_ribbon(
            price_vals=price_vals,
            auto_assign_ribbons=auto_assign_ribbons,
            variant=variant or self,
        )

    def _get_product_url(self, category=None, query_params=None, grouped_attributes_values=None):
        """Link straight to this variant's combination on the product page."""
        self.ensure_one()
        return self.website_url

    def _get_first_possible_variant_id(self):
        self.ensure_one()
        return self.id

    def _get_previewed_attribute_values(self, category=None, product_query_params=None):
        # A variant tile already *is* one combination; there is nothing to preview.
        return {}

    def _get_sales_prices(self, website):
        """Variant-level twin of `product.template._get_sales_prices`.

        Same output shape (`price_reduce`, optional `base_price`) so the standard
        tile markup renders unchanged, but priced per variant — which is the whole
        point of splitting the grid, since `price_extra` differs per combination.
        """
        if not self:
            return {}

        pricelist = request.pricelist
        currency = website.currency_id
        fiscal_position_sudo = request.fiscal_position
        date = fields.Date.context_today(self)

        pricelist_prices = pricelist._compute_price_rule(self, 1.0)
        comparison_prices_enabled = self.env['res.groups']._is_feature_enabled(
            'website_sale.group_product_price_comparison'
        )

        res = {}
        for variant in self:
            template = variant.product_tmpl_id
            pricelist_price, pricelist_rule_id = pricelist_prices[variant.id]

            product_taxes = variant.sudo().taxes_id._filter_taxes_by_company(self.env.company)
            taxes = fiscal_position_sudo.map_tax(product_taxes)

            base_price = None
            price_vals = {
                'price_reduce': template._apply_taxes_to_price(
                    pricelist_price, currency, product_taxes, taxes, variant, website=website,
                ),
            }
            pricelist_item = self.env['product.pricelist.item'].browse(pricelist_rule_id)
            if pricelist_item._show_discount_on_shop():
                pricelist_base_price = pricelist_item._compute_price_before_discount(
                    product=variant,
                    quantity=1.0,
                    date=date,
                    uom=variant.uom_id,
                    currency=currency,
                )
                if currency.compare_amounts(pricelist_base_price, pricelist_price) == 1:
                    base_price = pricelist_base_price
                    price_vals['base_price'] = template._apply_taxes_to_price(
                        base_price, currency, product_taxes, taxes, variant, website=website,
                    )

            if not base_price and comparison_prices_enabled and variant.compare_list_price:
                price_vals['base_price'] = variant.currency_id._convert(
                    variant.compare_list_price,
                    currency,
                    self.env.company,
                    date,
                    round=False,
                )

            res[variant.id] = price_vals

        return res
