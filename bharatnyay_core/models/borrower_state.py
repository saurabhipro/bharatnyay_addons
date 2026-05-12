# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatBorrowerState(models.Model):
    """State as on the spreadsheet (e.g. Punjab); not necessarily ``res.country.state``."""

    _name = 'bharat.borrower_state'
    _description = 'Borrower State'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    region_id = fields.Many2one('bharat.region', string='Default region')
    code = fields.Char(string='Code')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_borrower_state_name_uniq', 'unique(name)', 'This state already exists.'),
    ]
