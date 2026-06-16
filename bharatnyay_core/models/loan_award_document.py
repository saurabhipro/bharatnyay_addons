# -*- coding: utf-8 -*-
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BharatLoanAwardDocument(models.Model):
    _name = 'bharat.loan.award.document'
    _description = 'Loan award documents'
    _order = 'award_date desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    loan_number = fields.Char(related='loan_id.loan_number', store=True, readonly=True)
    case_number = fields.Char(related='loan_id.case_number', store=True, readonly=True)
    postal_dispatch_id = fields.Many2one(
        'bharat.loan.postal.dispatch',
        string='Postal dispatch',
        compute='_compute_postal_dispatch_id',
        store=True,
        index=True,
    )
    pod = fields.Char(related='postal_dispatch_id.pod', readonly=True)
    dispatch_date = fields.Date(related='postal_dispatch_id.dispatch_date', readonly=True)
    delivery_date = fields.Date(related='postal_dispatch_id.delivery_date', readonly=True)
    post_office_status_id = fields.Many2one(
        related='postal_dispatch_id.post_office_status_id',
        readonly=True,
    )
    award_type = fields.Selection(
        [('interim', 'Interim award'), ('final', 'Final award')],
        default='final',
        required=True,
    )
    award_date = fields.Datetime(string='Award date', default=fields.Datetime.now, required=True)
    award_notes = fields.Text(string='Award summary')
    draft_award_pdf = fields.Binary(string='Draft award letter', attachment=True)
    draft_award_pdf_filename = fields.Char(string='Draft filename')
    draft_generated_on = fields.Datetime(string='Draft generated on', copy=False)
    award_pdf = fields.Binary(string='Signed award PDF', attachment=True)
    award_pdf_filename = fields.Char(string='Signed filename')
    signed_on = fields.Datetime(string='Signed on', copy=False)
    is_signed = fields.Boolean(string='Signed copy uploaded', compute='_compute_is_signed', store=True)
    created_by_id = fields.Many2one('res.users', string='Recorded by', default=lambda self: self.env.user)

    @api.depends(
        'loan_id',
        'loan_id.postal_dispatch_ids.document_type',
        'loan_id.postal_dispatch_ids.pod',
        'loan_id.postal_dispatch_ids.post_office_status_id',
        'loan_id.postal_dispatch_ids.dispatch_date',
        'loan_id.postal_dispatch_ids.delivery_date',
    )
    def _compute_postal_dispatch_id(self):
        for rec in self:
            rec.postal_dispatch_id = False
            if not rec.loan_id:
                continue
            dispatch = rec.loan_id.postal_dispatch_ids.filtered(
                lambda d: d.document_type == 'award',
            )[:1]
            rec.postal_dispatch_id = dispatch.id if dispatch else False

    @api.depends('award_pdf')
    def _compute_is_signed(self):
        for rec in self:
            rec.is_signed = bool(rec.award_pdf)

    def _award_letter_report(self):
        return self.env.ref(
            'bharatnyay_core.action_report_bharat_loan_award_letter',
            raise_if_not_found=False,
        )

    def _attach_draft_award_letter(self):
        """Render draft award letter PDF and store on this document."""
        self.ensure_one()
        loan = self.loan_id
        if not loan:
            return False
        report = self._award_letter_report()
        if not report:
            _logger.warning('Award letter report not configured for award document %s', self.id)
            return False
        pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=loan.ids)
        ref = loan.loan_number or loan.case_number or loan.id
        filename = 'Award_Letter_Draft_%s.pdf' % ref
        self.write({
            'draft_award_pdf': base64.b64encode(pdf_bytes),
            'draft_award_pdf_filename': filename,
            'draft_generated_on': fields.Datetime.now(),
        })
        return True

    def action_download_award_letter(self):
        self.ensure_one()
        if self.award_type != 'final':
            raise UserError(_('Draft award letter applies to final awards only.'))
        if not self.draft_award_pdf:
            self._attach_draft_award_letter()
        report = self._award_letter_report()
        if not report:
            raise UserError(_('Award letter report is not configured.'))
        return report.report_action(self.loan_id)

    def action_upload_signed_award(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upload signed award'),
            'res_model': 'bharat.loan.award.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_loan_id': self.loan_id.id,
                'default_award_document_id': self.id,
            },
        }
