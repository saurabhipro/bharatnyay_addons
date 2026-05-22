# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatLoanLocation(models.Model):
    _name = 'bharat.loan_location'
    _description = 'Location (office / city)'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    branch_id = fields.Many2one('bharat.branch', string='Branch')
    state_id = fields.Many2one(
        'res.country.state',
        string='State',
        related='branch_id.borrower_state_id',
        store=True,
        readonly=True,
    )
    region_id = fields.Many2one(
        'bharat.region',
        string='Region',
        related='branch_id.region_id',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_loan_location_name_uniq', 'unique(name)', 'This location already exists.'),
    ]
