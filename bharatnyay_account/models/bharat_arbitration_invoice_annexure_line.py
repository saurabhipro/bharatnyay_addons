# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatArbitrationInvoiceAnnexureLine(models.Model):
    _name = 'bharat.arbitration.invoice.annexure.line'
    _description = 'Arbitration invoice annexure (per-case detail)'
    _order = 'sequence, id'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    billing_event_id = fields.Many2one(
        'bharat.loan.billing.event',
        string='Billing event',
        ondelete='set null',
        copy=False,
    )
    loan_id = fields.Many2one('bharat.loan', string='Case', ondelete='set null')
    loan_number = fields.Char(string='Loan number')
    case_number = fields.Char(string='BharatNyay case no.')
    customer_name = fields.Char(string='Borrower')
    milestone_code = fields.Char(string='Milestone code')
    milestone_label = fields.Char(string='Task')
    product_id = fields.Many2one('product.product', string='Product', ondelete='restrict')
    quantity = fields.Float(string='Qty', default=1.0, digits='Product Unit of Measure')
    unit_price = fields.Monetary(string='Rate per action', currency_field='currency_id')
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        compute='_compute_amount',
        store=True,
    )
    currency_id = fields.Many2one(related='move_id.currency_id', store=True, readonly=True)

    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for line in self:
            line.amount = (line.quantity or 0.0) * (line.unit_price or 0.0)
