# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatWriteoff(models.Model):
    _name = 'bharat.writeoff'
    _description = 'Write-off'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('bharat_writeoff_name_uniq', 'unique(name)', 'This write-off value already exists.'),
    ]
