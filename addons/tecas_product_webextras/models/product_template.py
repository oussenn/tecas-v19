from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    web_description = fields.Html(
        string="Description web",
        sanitize=True,
        sanitize_attributes=False,
        translate=True,
        help="Visible on the website under the product details. "
             "Applies to every variant unless a variant overrides it."
    )

    tech_sheet_pdf = fields.Binary(
        string="Fiche technique (PDF)",
        attachment=True,
        help="Upload a technical datasheet in PDF. "
             "Applies to every variant unless a variant overrides it."
    )
    tech_sheet_filename = fields.Char(string="Nom de fichier (PDF)")

    gallery_attachment_ids = fields.Many2many(
        "ir.attachment", "product_gallery_rel", "product_id", "attachment_id",
        string="Galerie d'images",
        domain=[("mimetype", "ilike", "image")],
        help="Upload multiple product images; shown as a gallery on the website. "
             "Applies to every variant unless a variant overrides it."
    )

    def _get_combination_info(
        self, combination=False, product_id=False, add_qty=1.0, uom_id=False, only_template=False,
    ):
        """Carry the resolved web extras along with the combination.

        The product page asks for this dict every time the visitor picks another
        variant, so returning the extras here is what lets the description, the
        datasheet and the gallery follow the selection without a page reload.
        """
        info = super()._get_combination_info(
            combination=combination, product_id=product_id, add_qty=add_qty,
            uom_id=uom_id, only_template=only_template,
        )
        variant = self.env['product.product'].browse(info.get('product_id') or 0)
        if variant.exists():
            info.update(variant._webx_payload())
        else:
            # No variant for this combination (dynamic or template-only view):
            # fall back to what the product itself carries.
            info.update({
                'webx_name': self.name or '',
                'webx_description': self.web_description or '',
                'webx_tech_sheet_url': self.env['product.product']._webx_tech_sheet_url(
                    'product.template', self.id, 'tech_sheet_pdf', self.tech_sheet_filename,
                ) if self.with_context(bin_size=True).tech_sheet_pdf else '',
                'webx_tech_sheet_filename': self.tech_sheet_filename or 'fiche-technique.pdf',
                'webx_gallery': [
                    {'id': attachment.id, 'name': attachment.name or ''}
                    for attachment in self.gallery_attachment_ids
                ],
            })
        return info
