# -*- coding: utf-8 -*-
from odoo import api, fields, models

BHARAT_ROLES = [
    ('case_manager', 'Case Manager'),
    ('arbitrator', 'Arbitrator'),
    ('borrower', 'Borrower'),
    ('lender', 'Lender'),
]


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
