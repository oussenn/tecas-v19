from odoo import api, fields, models
from odoo.http import request
from odoo.tools import is_html_empty

from .product_template import publish_gallery


class ProductProduct(models.Model):
    """Per-variant web extras, plus the helpers that let a variant stand in for a
    template in the shop grid.

    The variant fields are deliberately *not* named like the template ones. A
    variant already reads `web_description` and friends through `_inherits`
    delegation, so reusing those names would shadow the template value and make
    the fallback impossible to express.
    """
    _inherit = 'product.product'

    # --- Per-variant overrides. Empty means "use the template's value". --------
    variant_web_name = fields.Char(
        string="Nom web (variante)",
        translate=True,
        help="Overrides the product name on the website for this variant only. "
             "Leave empty to use the product name.",
    )
    variant_web_description = fields.Html(
        string="Description web (variante)",
        sanitize=True,
        sanitize_attributes=False,
        translate=True,
        help="Overrides the web description for this variant only. "
             "Leave empty to inherit the one set on the product.",
    )
    variant_tech_sheet_pdf = fields.Binary(
        string="Fiche technique (variante)",
        attachment=True,
        help="Datasheet for this variant only. Leave empty to inherit the "
             "product's datasheet.",
    )
    variant_tech_sheet_filename = fields.Char(string="Nom de fichier (PDF, variante)")
    variant_gallery_attachment_ids = fields.Many2many(
        'ir.attachment', 'product_variant_gallery_rel', 'variant_id', 'attachment_id',
        string="Galerie d'images (variante)",
        domain=[('mimetype', 'ilike', 'image')],
        help="Gallery for this variant only. Leave empty to inherit the product's gallery.",
    )

    # --- Resolved values: variant override first, product-level default second.
    webx_name = fields.Char(compute='_compute_webx', string="Nom affiché")
    webx_description = fields.Html(compute='_compute_webx', string="Description affichée")
    webx_tech_sheet_url = fields.Char(compute='_compute_webx')
    webx_tech_sheet_filename = fields.Char(compute='_compute_webx')

    @api.depends(
        'variant_web_name', 'variant_web_description', 'variant_tech_sheet_pdf',
        'variant_tech_sheet_filename', 'variant_gallery_attachment_ids',
        'product_tmpl_id.name', 'product_tmpl_id.web_description',
        'product_tmpl_id.tech_sheet_pdf', 'product_tmpl_id.tech_sheet_filename',
        'product_tmpl_id.gallery_attachment_ids',
    )
    def _compute_webx(self):
        # sudo: these drive the public product page, and both the datasheet and
        # the gallery live in ir.attachment, which website visitors cannot read.
        # bin_size keeps it cheap too: the binaries are only tested for presence,
        # never read, so the payloads stay out of the cache.
        for variant in self:
            variant_sudo = variant.sudo()
            template_sudo = variant.product_tmpl_id.sudo()
            sized_variant = variant_sudo.with_context(bin_size=True)
            sized_template = template_sudo.with_context(bin_size=True)

            # Each field falls back on its own: overriding the description does
            # not drag the name along with it.
            variant.webx_name = (variant_sudo.variant_web_name or '').strip() or template_sudo.name

            # The HTML editor leaves "<p><br></p>" behind when you clear a field,
            # which is truthy but renders as nothing — treat it as empty so the
            # product's description comes back instead of a blank block.
            variant_description = variant_sudo.variant_web_description
            template_description = template_sudo.web_description
            if not is_html_empty(variant_description):
                variant.webx_description = variant_description
            elif not is_html_empty(template_description):
                variant.webx_description = template_description
            else:
                variant.webx_description = False
            if sized_variant.variant_tech_sheet_pdf:
                filename = variant_sudo.variant_tech_sheet_filename
                variant.webx_tech_sheet_url = self._webx_tech_sheet_url(
                    'product.product', variant.id, 'variant_tech_sheet_pdf', filename,
                )
            elif sized_template.tech_sheet_pdf:
                filename = template_sudo.tech_sheet_filename
                variant.webx_tech_sheet_url = self._webx_tech_sheet_url(
                    'product.template', template_sudo.id, 'tech_sheet_pdf', filename,
                )
            else:
                filename = False
                variant.webx_tech_sheet_url = False
            variant.webx_tech_sheet_filename = filename or 'fiche-technique.pdf'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        publish_gallery(records.variant_gallery_attachment_ids)
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'variant_gallery_attachment_ids' in vals:
            publish_gallery(self.variant_gallery_attachment_ids)
        return result

    def _webx_gallery(self):
        """Resolved gallery: the variant's images, else the product's.

        A method rather than a computed Many2many because it returns
        ir.attachment records the public user has no ACL for. Reading them here
        is done under sudo; being SEEN is a separate matter, handled by
        publish_gallery() when the images are attached — the browser fetches
        each one itself, and that request is checked on its own.

        Called on NOTHING it answers nothing, rather than raising. The product
        page hands it `product_variant`, which is empty for a template whose
        variants have all been archived — and an "Expected singleton" from a
        template attribute is a 500 on the whole page, not a missing gallery.
        That is what /shop/p-30 was serving to everyone who reached it from
        Google.
        """
        if not self:
            return self.env['ir.attachment'].browse()
        self.ensure_one()
        variant_sudo = self.sudo()
        return (
            variant_sudo.variant_gallery_attachment_ids
            or variant_sudo.product_tmpl_id.gallery_attachment_ids
        )

    @api.model
    def _webx_tech_sheet_url(self, model, res_id, field, filename):
        return '/web/content?model=%s&id=%s&field=%s&filename=%s&download=1' % (
            model, res_id, field, filename or 'fiche-technique.pdf',
        )

    def _webx_payload(self):
        """Resolved extras in the shape the product page's JS expects."""
        self.ensure_one()
        return {
            'webx_name': self.webx_name or '',
            'webx_description': self.webx_description or '',
            'webx_tech_sheet_url': self.webx_tech_sheet_url or '',
            'webx_tech_sheet_filename': self.webx_tech_sheet_filename or '',
            'webx_gallery': [
                {'id': attachment.id, 'name': attachment.name or ''}
                for attachment in self._webx_gallery()
            ],
        }

    # --- Shop grid: let a variant stand in for a template ----------------------
    # The shop tile calls these `product.template` helpers on whatever record it
    # is handed; these delegates keep the standard markup working for variants.

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
