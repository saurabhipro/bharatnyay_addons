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
