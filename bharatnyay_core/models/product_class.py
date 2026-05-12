# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatProductClass(models.Model):
    _name = 'bharat.product_class'
    _description = 'Product class'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_product_class_name_uniq', 'unique(name)', 'This product class already exists.'),
    ]
