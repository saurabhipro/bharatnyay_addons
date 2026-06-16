# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatLoanBillingEventAccount(models.Model):
    _inherit = 'bharat.loan.billing.event'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        ondelete='set null',
        copy=False,
        index=True,
    )
    annexure_line_id = fields.Many2one(
        'bharat.arbitration.invoice.annexure.line',
        string='Annexure row',
        ondelete='set null',
        copy=False,
    )
