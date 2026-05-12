# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatUserRoleAssignment(models.Model):
    _name = 'bharat.user.role.assignment'
    _description = 'BharatNyay User Role Assignment'
    _order = 'role, user_id, id'

    user_id = fields.Many2one('res.users', string='User', required=True, index=True)
    role = fields.Selection(
        [
            ('case_manager', 'Case Manager'),
            ('arbitrator', 'Arbitrator'),
            ('borrower', 'Borrower'),
            ('lender', 'Lender'),
        ],
        string='Role',
        required=True,
        default='case_manager',
        index=True,
    )
    active = fields.Boolean(default=True)

    region_id = fields.Many2one('bharat.region', string='Region', index=True)
    borrower_state_id = fields.Many2one('bharat.borrower_state', string='State', index=True)
    branch_id = fields.Many2one('bharat.branch', string='Branch', index=True)
    location_id = fields.Many2one('bharat.loan_location', string='Location', index=True)

    note = fields.Char(string='Notes')

    _sql_constraints = [
        (
            'bharat_user_role_assignment_unique',
            'unique(user_id, role, region_id, borrower_state_id, branch_id, location_id)',
            'This exact user-role-location assignment already exists.',
        ),
    ]

    @api.onchange('location_id')
    def _onchange_location_id(self):
        for rec in self:
            loc = rec.location_id
            if not loc or not loc.branch_id:
                continue
            rec.branch_id = loc.branch_id
            if loc.branch_id.borrower_state_id:
                rec.borrower_state_id = loc.branch_id.borrower_state_id
            if loc.branch_id.region_id:
                rec.region_id = loc.branch_id.region_id

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        for rec in self:
            b = rec.branch_id
            if not b:
                continue
            if b.borrower_state_id:
                rec.borrower_state_id = b.borrower_state_id
            if b.region_id:
                rec.region_id = b.region_id

    @api.onchange('borrower_state_id')
    def _onchange_borrower_state_id(self):
        for rec in self:
            st = rec.borrower_state_id
            if st and st.region_id and not rec.region_id:
                rec.region_id = st.region_id
