# -*- coding: utf-8 -*-
from odoo import api, fields, models

BHARAT_ROLES = [
    ('admin', 'Admin'),
    ('case_manager', 'Case Manager'),
    ('arbitrator', 'Arbitrator'),
    ('borrower', 'Borrower'),
    ('lender', 'Lender'),
]

# Operational role → security group xml id
BHARAT_ROLE_GROUP_XMLIDS = {
    'admin': 'bharatnyay_core.group_bharat_admin',
    'case_manager': 'bharatnyay_core.group_bharat_case_manager',
    'arbitrator': 'bharatnyay_core.group_bharat_arbitrator',
    'borrower': 'bharatnyay_core.group_bharat_borrower',
    'lender': 'bharatnyay_core.group_bharat_lender',
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    bharat_role = fields.Selection(
        BHARAT_ROLES,
        string='Operational role',
        index=True,
    )
    bharat_region_id = fields.Many2one('bharat.region', string='Region', index=True)
    bharat_borrower_state_id = fields.Many2one('bharat.borrower_state', string='State', index=True)
    bharat_branch_id = fields.Many2one('bharat.branch', string='Branch', index=True)
    bharat_location_id = fields.Many2one('bharat.loan_location', string='Location', index=True)
    bharat_role_note = fields.Char(string='Role notes')

    @api.model
    def _bharat_operational_groups(self):
        """All BharatNyay role groups in the operational category (for add/remove)."""
        category = self.env.ref(
            'bharatnyay_core.module_category_bharatnyay_roles',
            raise_if_not_found=False,
        )
        if not category:
            groups = self.env['res.groups']
            for xmlid in BHARAT_ROLE_GROUP_XMLIDS.values():
                groups |= self.env.ref(xmlid, raise_if_not_found=False)
            return groups
        return self.env['res.groups'].search([('category_id', '=', category.id)])

    def _bharat_group_for_role(self, role):
        if not role:
            return self.env['res.groups']
        xmlid = BHARAT_ROLE_GROUP_XMLIDS.get(role)
        if not xmlid:
            return self.env['res.groups']
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _sync_bharat_role_groups(self):
        """Assign exactly one BharatNyay role group matching ``bharat_role``."""
        all_role_groups = self._bharat_operational_groups()
        if not all_role_groups:
            return

        for user in self:
            target = user._bharat_group_for_role(user.bharat_role)
            # Drop every BharatNyay role group (incl. implied) before applying the new one.
            stale = user.groups_id & all_role_groups
            commands = [(3, gid) for gid in stale.ids]
            if target:
                commands.append((4, target.id))
            if commands:
                user.sudo().write({'groups_id': commands})

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users.filtered('bharat_role')._sync_bharat_role_groups()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'bharat_role' in vals:
            self._sync_bharat_role_groups()
        return res

    @api.onchange('bharat_location_id')
    def _onchange_bharat_location_id(self):
        for user in self:
            loc = user.bharat_location_id
            if not loc or not loc.branch_id:
                continue
            user.bharat_branch_id = loc.branch_id
            if loc.branch_id.borrower_state_id:
                user.bharat_borrower_state_id = loc.branch_id.borrower_state_id
            if loc.branch_id.region_id:
                user.bharat_region_id = loc.branch_id.region_id

    @api.onchange('bharat_branch_id')
    def _onchange_bharat_branch_id(self):
        for user in self:
            branch = user.bharat_branch_id
            if not branch:
                continue
            if branch.borrower_state_id:
                user.bharat_borrower_state_id = branch.borrower_state_id
            if branch.region_id:
                user.bharat_region_id = branch.region_id

    @api.onchange('bharat_borrower_state_id')
    def _onchange_bharat_borrower_state_id(self):
        for user in self:
            state = user.bharat_borrower_state_id
            if state and state.region_id and not user.bharat_region_id:
                user.bharat_region_id = state.region_id
