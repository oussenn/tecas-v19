from odoo import models
from odoo.addons.mail.tools.discuss import Store

ALWAYS_VISIBLE_LOGINS = ['info@albatros.ma', 'ra@tecas.ma']

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        if 'user_id' in vals:
            for partner in self:
                channels = self.env['discuss.channel'].sudo().search([
                    ('whatsapp_partner_id', '=', partner.id),
                    ('channel_type', '=', 'whatsapp'),
                ])
                if not channels:
                    continue

                # Build always-visible partner IDs
                always_visible_ids = self.env['res.users'].sudo().search([
                    ('login', 'in', ALWAYS_VISIBLE_LOGINS)
                ]).mapped('partner_id.id')

                new_vendor = self.env['res.users'].sudo().browse(vals['user_id']).partner_id if vals['user_id'] else self.env['res.partner']

                for channel in channels:
                    if not vals['user_id']:
                        # Unassigned — skip sync, visible to everyone via record rule
                        continue

                    protected_ids = [partner.id, new_vendor.id] + always_visible_ids

                    for member in channel.sudo().channel_member_ids:
                        if member.partner_id.id not in protected_ids:
                            removed_partner = member.partner_id
                            member.sudo().unlink()
                            self.env.cr.commit()
                            store = Store(bus_channel=removed_partner.main_user_id or removed_partner)
                            store.add(channel, {"close_chat_window": True, "isLocallyPinned": False})
                            store.bus_send()

                    existing = self.env['discuss.channel.member'].sudo().search([
                        ('channel_id', '=', channel.id),
                        ('partner_id', '=', new_vendor.id)
                    ])
                    if not existing:
                        channel.sudo().add_members(partner_ids=[new_vendor.id])

        return super().write(vals)
