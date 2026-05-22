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

    @api.model
    def bharatnyay_ensure_demo_case_manager(self):
        """Create or align the sandbox case manager user (module data XML)."""
        login = 'bn.demo.case.manager'
        Users = self.sudo()
        user = Users.search([('login', '=', login)], limit=1)
        company = self.env.ref('base.main_company', raise_if_not_found=False)
        vals = {
            'name': 'Demo Case Manager',
            'email': 'manager.demo@bharatnyay.example.com',
            'bharat_role': 'case_manager',
        }
        if company:
            vals['company_id'] = company.id
            vals['company_ids'] = [(6, 0, [company.id])]
        if not user:
            vals.update({
                'login': login,
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
            })
            user = Users.create(vals)
            user.password = '1234'
            return user
        if not user.bharat_role:
            user.write(vals)
        user._sync_bharat_role_groups()
        return user

    @api.model
    def bharatnyay_ensure_demo_lender(self):
        """Create or align the sandbox lender user (module data XML)."""
        login = 'bn.demo.lender'
        Users = self.sudo()
        user = Users.search([('login', '=', login)], limit=1)
        company = self.env.ref('base.main_company', raise_if_not_found=False)
        vals = {
            'name': 'Demo Lender',
            'email': 'lender.demo@bharatnyay.example.com',
            'bharat_role': 'lender',
        }
        if company:
            vals['company_id'] = company.id
            vals['company_ids'] = [(6, 0, [company.id])]
        if not user:
            vals.update({
                'login': login,
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
            })
            user = Users.create(vals)
            user.password = '1234'
            return user
        if not user.bharat_role:
            user.write(vals)
        elif company and company.id not in user.company_ids.ids:
            user.write({'company_ids': [(4, company.id)]})
        user._sync_bharat_role_groups()
        return user

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
