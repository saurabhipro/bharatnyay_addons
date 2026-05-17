# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BharatArbitratorBlockout(models.Model):
    _name = 'bharat.arbitrator.blockout'
    _description = 'Arbitrator non-working day / holiday window'
    _order = 'user_id, date_start'

    user_id = fields.Many2one(
        'res.users',
        string='Arbitrator',
        required=True,
        index=True,
        domain=lambda self: self.env['bharat.loan']._domain_arbitrator_users(),
    )
    date_start = fields.Date(required=True, index=True)
    date_end = fields.Date(required=True, index=True)
    note = fields.Char()

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_('Block-out end date must be on or after the start date.'))
