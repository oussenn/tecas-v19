import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def publish_gallery(attachments):
    """Let a visitor who is not logged in actually see a gallery image.

    The gallery renders /web/image/<attachment id>, and that is a second HTTP
    request made by the BROWSER — rendering the page under sudo does nothing
    for it. ir.attachment is not readable by the public user, so Odoo answers
    those requests with its grey placeholder (200, 6 kB of PNG, no error
    anywhere), which is why the galleries looked fine to anyone logged in and
    were blank to everybody else.

    Marking the attachment public is the whole fix: it is a product photo on a
    public product page, which is precisely what the flag is for.

    Only images are published. The field's domain filters the picker to images
    but a domain is not a constraint, and a contract dropped into the gallery
    field by accident must not be made world-readable by this.
    """
    attachments = attachments.sudo()
    images = attachments.filtered(
        lambda a: not a.public and (a.mimetype or '').startswith('image/'))
    if images:
        images.write({'public': True})
    refused = attachments.filtered(
        lambda a: not a.public and not (a.mimetype or '').startswith('image/'))
    if refused:
        _logger.warning(
            'webextras: %s left private, not an image: %s',
            len(refused), ', '.join('%s (%s)' % (a.name, a.mimetype) for a in refused))
    return len(images)


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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        publish_gallery(records.gallery_attachment_ids)
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'gallery_attachment_ids' in vals:
            publish_gallery(self.gallery_attachment_ids)
        return result

    @api.model
    def _webx_publish_galleries(self):
        """Publish every gallery image already in the database.

        Called from views/website_template.xml on install and on every upgrade,
        so a site whose galleries were uploaded before this existed is repaired
        by the deploy rather than by remembering to run something.
        """
        templates = self.sudo().search([])
        variants = self.env['product.product'].sudo().search([])
        published = publish_gallery(
            templates.gallery_attachment_ids | variants.variant_gallery_attachment_ids)
        if published:
            _logger.info('webextras: %s gallery image(s) made visible to visitors', published)

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
