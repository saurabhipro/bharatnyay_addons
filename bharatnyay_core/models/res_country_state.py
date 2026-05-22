# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCountryState(models.Model):
    _inherit = 'res.country.state'

    region_id = fields.Many2one(
        'bharat.region',
        string='Region',
        ondelete='set null',
        help='BharatNyay region used for loan geography and dashboards.',
    )
