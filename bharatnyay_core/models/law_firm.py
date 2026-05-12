# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatLawFirm(models.Model):
    _name = 'bharat.law_firm'
    _description = 'Law firm'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    phone = fields.Char(string='Phone')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_law_firm_name_uniq', 'unique(name)', 'This law firm already exists.'),
    ]
