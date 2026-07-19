# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # Uniqueness helpers
    # ------------------------------------------------------------------

    def _check_phone_unique(self, phone, exclude_ids=None):
        if not phone:
            return
        domain = [('phone', '=', phone), ('id', 'not in', exclude_ids or [])]
        duplicate = self.sudo().search(domain, limit=1)
        if duplicate:
            raise ValidationError(_(
                'Le numéro de téléphone "%s" est déjà utilisé par le contact "%s".'
            ) % (phone, duplicate.name or duplicate.id))

    def _check_ice_unique(self, ice, exclude_ids=None):
        if not ice:
            return
        domain = [('x_studio_ice', '=', ice), ('id', 'not in', exclude_ids or [])]
        duplicate = self.sudo().search(domain, limit=1)
        if duplicate:
            raise ValidationError(_(
                'Le numéro ICE "%s" est déjà utilisé par le contact "%s".'
            ) % (ice, duplicate.name or duplicate.id))

    # ------------------------------------------------------------------
    # Create — validate required fields + uniqueness on new records
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_type = vals.get('company_type') or (
                'company' if vals.get('is_company') else 'person'
            )
            if company_type == 'person' and not vals.get('phone'):
                raise UserError(_("Le numéro de téléphone est obligatoire pour créer un contact de type Individu."))
            if company_type == 'company' and not vals.get('x_studio_ice'):
                raise UserError(_("Le numéro ICE est obligatoire pour créer un contact de type Société."))
            self._check_phone_unique(vals.get('phone'))
            self._check_ice_unique(vals.get('x_studio_ice'))
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Write — only re-validate when phone or ICE is actually being changed
    # ------------------------------------------------------------------

    def write(self, vals):
        if 'phone' in vals:
            self._check_phone_unique(vals['phone'], exclude_ids=self.ids)
        if 'x_studio_ice' in vals:
            self._check_ice_unique(vals['x_studio_ice'], exclude_ids=self.ids)
        return super().write(vals)
