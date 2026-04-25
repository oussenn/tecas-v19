from odoo import fields, models

class ProductTemplate(models.Model):
    _inherit = "product.template"

    web_description = fields.Html(
        string="Description web",
        sanitize=True,
        sanitize_attributes=False,
        translate=True,
        help="Visible on the website under the product details."
    )

    tech_sheet_pdf = fields.Binary(
        string="Fiche technique (PDF)",
        attachment=True,
        help="Upload a technical datasheet in PDF."
    )
    tech_sheet_filename = fields.Char(string="Nom de fichier (PDF)")

    gallery_attachment_ids = fields.Many2many(
        "ir.attachment", "product_gallery_rel", "product_id", "attachment_id",
        string="Galerie d’images",
        domain=[("mimetype", "ilike", "image")],
        help="Upload multiple product images; shown as a gallery on the website."
    )
