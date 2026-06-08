from odoo import models

_CTX = '_tecas_sync_salesman'


class CrmLeadSyncSalesman(models.Model):
    _inherit = 'crm.lead'

    def write(self, vals):
        res = super().write(vals)
        if 'user_id' in vals and not self.env.context.get(_CTX):
            for lead in self:
                if lead.partner_id:
                    lead.partner_id.with_context(**{_CTX: True}).sudo().write(
                        {'user_id': lead.user_id.id if lead.user_id else False}
                    )
        return res


class ResPartnerSyncSalesman(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        res = super().write(vals)
        if 'user_id' in vals and not self.env.context.get(_CTX):
            for partner in self:
                lead = self.env['crm.lead'].sudo().search(
                    [('partner_id', '=', partner.id), ('active', '=', True)],
                    order='create_date desc',
                    limit=1,
                )
                if lead:
                    lead.with_context(**{_CTX: True}).sudo().write(
                        {'user_id': partner.user_id.id if partner.user_id else False}
                    )
        return res
