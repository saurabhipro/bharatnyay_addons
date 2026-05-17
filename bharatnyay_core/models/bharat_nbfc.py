# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatNbfc(models.Model):
    _name = 'bharat.nbfc'
    _description = 'NBFC / lender (billing scope)'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    code = fields.Char(string='Short code', index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Linked partner',
        help='Optional accounting/billing contact.',
    )
    active = fields.Boolean(default=True)
