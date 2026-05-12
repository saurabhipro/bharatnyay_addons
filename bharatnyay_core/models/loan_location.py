# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatLoanLocation(models.Model):
    _name = 'bharat.loan_location'
    _description = 'Location (office / city)'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    branch_id = fields.Many2one('bharat.branch', string='Branch')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_loan_location_name_uniq', 'unique(name)', 'This location already exists.'),
    ]
