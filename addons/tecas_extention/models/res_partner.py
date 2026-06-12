# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_type = vals.get('company_type') or (
                'company' if vals.get('is_company') else 'person'
            )
            if company_type == 'person' and not vals.get('phone'):
                raise UserError(_("Le numéro de téléphone est obligatoire pour créer un contact de type Individu."))
            if company_type == 'company' and not vals.get('company_registry'):
                raise UserError(_("Le numéro ICE est obligatoire pour créer un contact de type Société."))
        return super().create(vals_list)
