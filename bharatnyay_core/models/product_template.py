# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BHARAT_ARBITRATION_STAGE_SELECTION = [
    ('notice_1', 'Notice 1'),
    ('notice_2', 'Notice 2'),
    ('notice_3', 'Notice 3'),
    ('interim_order_1', 'Interim Order 1'),
    ('hearing_1', 'Hearing 1'),
    ('hearing_2', 'Hearing 2'),
    ('hearing_3', 'Hearing 3'),
    ('award', 'Award'),
]

DEFAULT_BILLING_PRODUCTS = (
    ('notice_1', 'ODR — Notice 1', 25.0),
    ('notice_2', 'ODR — Notice 2', 25.0),
    ('notice_3', 'ODR — Notice 3', 25.0),
    ('interim_order_1', 'ODR — Interim Order 1', 35.0),
    ('hearing_1', 'ODR — Hearing 1', 50.0),
    ('hearing_2', 'ODR — Hearing 2', 50.0),
    ('hearing_3', 'ODR — Hearing 3', 50.0),
    ('award', 'ODR — Award', 75.0),
)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    bharat_arbitration_stage = fields.Selection(
        BHARAT_ARBITRATION_STAGE_SELECTION,
        string='Arbitration billing stage',
        index=True,
        help='When set, this product is the standard SKU for that milestone on annexure invoices '
        '(customer invoices). Use Sales Price as the default rate; NBFC-specific amounts via partner pricelists.',
    )

    @api.constrains('bharat_arbitration_stage')
    def _check_bharat_stage_unique(self):
        for tmpl in self:
            st = tmpl.bharat_arbitration_stage
            if not st:
                continue
            if self.search_count([
                ('bharat_arbitration_stage', '=', st),
                ('id', '!=', tmpl.id),
            ]):
                raise ValidationError(
                    _('Only one product can be assigned to arbitration stage “%s”.')
                    % dict(BHARAT_ARBITRATION_STAGE_SELECTION).get(st, st)
                )

    @api.model
    def _sync_default_billing_products(self):
        """Create one service SKU per arbitration stage when missing (sample rates)."""
        labels = dict(BHARAT_ARBITRATION_STAGE_SELECTION)
        for stage, name, price in DEFAULT_BILLING_PRODUCTS:
            if stage not in labels:
                continue
            existing = self.search([('bharat_arbitration_stage', '=', stage)], limit=1)
            if existing:
                continue
            self.create({
                'name': name,
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'bharat_arbitration_stage': stage,
                'list_price': price,
            })
        return True
