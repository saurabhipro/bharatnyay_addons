# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatBranch(models.Model):
    _name = 'bharat.branch'
    _description = 'Branch'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    code = fields.Char(string='Code')
    region_id = fields.Many2one('bharat.region', string='Region')
    borrower_state_id = fields.Many2one(
        'res.country.state',
        string='State',
        domain="[('country_id.code', '=', 'IN')]",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_branch_name_uniq', 'unique(name)', 'This branch already exists.'),
    ]
