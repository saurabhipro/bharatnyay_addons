# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatBranch(models.Model):
    _name = 'bharat.branch'
    _description = 'Branch'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    code = fields.Char(string='Code')
    region_id = fields.Many2one('bharat.region', string='Region')
    borrower_state_id = fields.Many2one('bharat.borrower_state', string='State')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_branch_name_uniq', 'unique(name)', 'This branch already exists.'),
    ]

    @api.onchange('borrower_state_id')
    def _onchange_borrower_state_id(self):
        for rec in self:
            if (
                rec.borrower_state_id
                and rec.borrower_state_id.region_id
                and not rec.region_id
            ):
                rec.region_id = rec.borrower_state_id.region_id
