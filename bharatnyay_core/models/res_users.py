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
    bharat_borrower_state_id = fields.Many2one(
        'res.country.state',
        string='State',
        index=True,
    )
    bharat_branch_ids = fields.Many2many(
        'bharat.branch',
        'bharat_res_users_branch_rel',
        'user_id',
        'branch_id',
        string='Branches',
    )
    bharat_location_ids = fields.Many2many(
        'bharat.loan_location',
        'bharat_res_users_location_rel',
        'user_id',
        'location_id',
        string='Locations',
    )
    bharat_role_note = fields.Char(string='Role notes')
    bharat_loan_count = fields.Integer(
        string='Assigned cases',
        compute='_compute_bharat_loan_count',
    )

    def _bharat_loan_assignment_domain(self):
        """Domain of ``bharat.loan`` rows assigned to this user by operational role."""
        self.ensure_one()
        if self.bharat_role == 'case_manager':
            return [('case_manager_id', '=', self.id)]
        if self.bharat_role == 'arbitrator':
            return [('arbitrator_id', '=', self.id)]
        if self.bharat_role == 'lender':
            return ['|', ('company_id', '=', False), ('company_id', 'in', self.company_ids.ids)]
        if self.bharat_role == 'admin':
            return []
        return [('id', '=', 0)]

    @api.depends('bharat_role', 'company_ids')
    def _compute_bharat_loan_count(self):
        Loan = self.env['bharat.loan'].sudo()
        for user in self:
            user.bharat_loan_count = Loan.search_count(user._bharat_loan_assignment_domain())

    def action_view_bharat_loans(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('bharatnyay_core.action_bharat_loan')
        action['domain'] = self._bharat_loan_assignment_domain()
        action['context'] = dict(self.env.context)
        return action

    @api.model
    def _find_case_manager_for_scope(self, branch_id=False, location_id=False):
        """Return the first active case manager whose branch/location scope matches."""
        if branch_id and not location_id:
            branch = self.env['bharat.branch'].browse(branch_id)
            if branch.location_id:
                location_id = branch.location_id.id
        if not branch_id and not location_id:
            return False

        candidates = self.search([
            ('bharat_role', '=', 'case_manager'),
            ('active', '=', True),
        ], order='id')
        for user in candidates:
            if not user.bharat_branch_ids and not user.bharat_location_ids:
                continue
            if user.bharat_branch_ids and (not branch_id or branch_id not in user.bharat_branch_ids.ids):
                continue
            if user.bharat_location_ids and (not location_id or location_id not in user.bharat_location_ids.ids):
                continue
            return user.id
        return False

    @api.model
    def _find_arbitrator_for_assignment(self):
        """Return the active arbitrator with the fewest assigned cases (round-robin)."""
        candidates = self.search([
            ('bharat_role', '=', 'arbitrator'),
            ('active', '=', True),
            ('share', '=', False),
        ], order='id')
        if not candidates:
            return False

        Loan = self.env['bharat.loan'].sudo()
        best = candidates[0]
        min_count = Loan.search_count([('arbitrator_id', '=', best.id)])
        for user in candidates[1:]:
            count = Loan.search_count([('arbitrator_id', '=', user.id)])
            if count < min_count:
                best = user
                min_count = count
        return best.id

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
        if any(
            'bharat_role' in vals or 'bharat_branch_ids' in vals or 'bharat_location_ids' in vals
            for vals in vals_list
        ):
            users.filtered(
                lambda u: u.bharat_role == 'case_manager' and u.active
            )._bharat_trigger_loan_case_manager_recompute()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'bharat_role' in vals:
            self._sync_bharat_role_groups()
        if {'bharat_role', 'bharat_branch_ids', 'bharat_location_ids', 'active'} & set(vals):
            self.filtered(
                lambda u: u.bharat_role == 'case_manager' and u.active
            )._bharat_trigger_loan_case_manager_recompute()
        return res

    def _bharat_trigger_loan_case_manager_recompute(self):
        self.env['bharat.loan'].sudo()._recompute_auto_case_managers()

    @api.onchange('bharat_region_id')
    def _onchange_bharat_region_id(self):
        for user in self:
            if user.bharat_borrower_state_id and (
                not user.bharat_region_id
                or user.bharat_borrower_state_id.region_id != user.bharat_region_id
            ):
                user.bharat_borrower_state_id = False
            if user.bharat_region_id:
                user.bharat_location_ids = user.bharat_location_ids.filtered(
                    lambda loc: loc.region_id == user.bharat_region_id
                )
                user.bharat_branch_ids = user.bharat_branch_ids.filtered(
                    lambda branch: branch.region_id == user.bharat_region_id
                )
            else:
                user.bharat_location_ids = False
                user.bharat_branch_ids = False

    @api.onchange('bharat_branch_ids')
    def _onchange_bharat_branch_ids(self):
        for user in self:
            branches = user.bharat_branch_ids
            if not branches:
                continue
            branch = branches[0]
            if branch.region_id:
                user.bharat_region_id = branch.region_id
            if branch.borrower_state_id:
                user.bharat_borrower_state_id = branch.borrower_state_id
            elif branch.location_id and branch.location_id.state_id:
                user.bharat_borrower_state_id = branch.location_id.state_id
            locations = branches.mapped('location_id')
            if locations:
                user.bharat_location_ids = user.bharat_location_ids | locations

    @api.onchange('bharat_location_ids')
    def _onchange_bharat_location_ids(self):
        for user in self:
            locations = user.bharat_location_ids
            if not locations:
                continue
            location = locations[0]
            if location.state_id:
                user.bharat_borrower_state_id = location.state_id
            if location.region_id:
                user.bharat_region_id = location.region_id
            user.bharat_branch_ids = user.bharat_branch_ids.filtered(
                lambda branch: not branch.location_id or branch.location_id in locations
            )

    @api.onchange('bharat_borrower_state_id')
    def _onchange_bharat_borrower_state_id(self):
        for user in self:
            state = user.bharat_borrower_state_id
            if state and state.region_id:
                user.bharat_region_id = state.region_id
            if state:
                user.bharat_location_ids = user.bharat_location_ids.filtered(
                    lambda loc: loc.state_id == state
                )
                user.bharat_branch_ids = user.bharat_branch_ids.filtered(
                    lambda branch: branch.borrower_state_id == state
                )
            else:
                user.bharat_location_ids = False
                user.bharat_branch_ids = False

