# -*- coding: utf-8 -*-
import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanInterimOrder(models.Model):
    _name = 'bharat.loan.interim.order'
    _description = 'Loan interim orders'
    _order = 'order_date desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    hearing_line_id = fields.Many2one('bharat.loan.hearing.line', string='Related hearing')
    order_type = fields.Selection(
        selection='_interim_order_type_selection',
        string='Interim order type',
        index=True,
    )
    purpose = fields.Char(string='Purpose')
    typical_loan_type = fields.Char(string='Typical loan type')
    passed_by = fields.Selection(
        selection='_interim_order_passed_by_selection',
        string='Passed by',
    )
    common_directions = fields.Text(string='Common directions')
    order_date = fields.Datetime(string='Order date', default=fields.Datetime.now, required=True)
    amount = fields.Monetary(string='Interim amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    notes = fields.Text(string='Additional notes / rationale')
    draft_body_html = fields.Html(string='Draft order body', sanitize=False)
    order_pdf = fields.Binary(string='Interim order PDF', attachment=True)
    order_pdf_filename = fields.Char(string='Interim PDF filename')
    signed_on = fields.Datetime(string='Signed on', copy=False)
    is_signed = fields.Boolean(string='Signed copy uploaded', compute='_compute_is_signed', store=True)
    created_by_id = fields.Many2one('res.users', string='Recorded by', default=lambda self: self.env.user)

    @api.depends('order_pdf', 'signed_on')
    def _compute_is_signed(self):
        for rec in self:
            rec.is_signed = bool(rec.order_pdf and rec.signed_on)

    @api.model
    def _interim_order_type_selection(self):
        from .interim_order_types import INTERIM_ORDER_TYPE_SELECTION
        return INTERIM_ORDER_TYPE_SELECTION

    @api.model
    def _interim_order_passed_by_selection(self):
        from .interim_order_types import INTERIM_ORDER_PASSED_BY_SELECTION
        return INTERIM_ORDER_PASSED_BY_SELECTION

    @api.onchange('order_type')
    def _onchange_order_type(self):
        from .interim_order_types import interim_order_meta
        for rec in self:
            if not rec.order_type:
                continue
            meta = interim_order_meta(rec.order_type)
            rec.purpose = meta.get('purpose')
            rec.typical_loan_type = meta.get('typical_loan_type')
            rec.passed_by = meta.get('passed_by')
            rec.common_directions = meta.get('common_directions')

    def _interim_order_report(self):
        return self.env.ref(
            'bharatnyay_core.action_report_bharat_loan_interim_order_document',
            raise_if_not_found=False,
        )

    def _attach_order_pdf(self):
        """Render draft interim order PDF from stored HTML body."""
        self.ensure_one()
        if not self.draft_body_html:
            return False
        report = self._interim_order_report()
        if not report:
            return False
        pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=self.ids)
        ref = self.loan_id.loan_number or self.loan_id.case_number or self.loan_id.id
        type_code = self.order_type or 'interim'
        filename = 'Interim_Order_%s_%s.pdf' % (type_code, ref)
        self.write({
            'order_pdf': base64.b64encode(pdf_bytes),
            'order_pdf_filename': filename,
        })
        return True

    def action_download_order_pdf(self):
        self.ensure_one()
        if not self.order_pdf:
            self._attach_order_pdf()
        if not self.order_pdf:
            raise UserError(_('Interim order PDF is not available yet.'))
        filename = self.order_pdf_filename or 'Interim_Order.pdf'
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content/?model=%s&id=%s&field=order_pdf&filename=%s&download=true'
            ) % (self._name, self.id, filename),
            'target': 'self',
        }


