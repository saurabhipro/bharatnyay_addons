# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatRegion(models.Model):
    _name = 'bharat.region'
    _description = 'Region'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    code = fields.Char(string='Code')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_region_name_uniq', 'unique(name)', 'This region already exists.'),
    ]
