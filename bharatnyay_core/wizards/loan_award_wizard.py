# -*- coding: utf-8 -*-

import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanAwardUploadWizard(models.TransientModel):
    _name = 'bharat.loan.award.upload.wizard'
    _description = 'Upload signed award letter'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    award_document_id = fields.Many2one(
        'bharat.loan.award.document',
        string='Award record',
        required=True,
        readonly=True,
    )
    case_display = fields.Char(string='Case', compute='_compute_meta', readonly=True)
    loan_display = fields.Char(string='Loan', compute='_compute_meta', readonly=True)

    signed_award_pdf = fields.Binary(string='Signed award PDF', required=True)
    signed_award_pdf_filename = fields.Char(string='Signed PDF filename')
    signed_on = fields.Datetime(
        string='Signed on',
        required=True,
        default=fields.Datetime.now,
    )
    award_notes = fields.Text(string='Notes')

    @api.depends('loan_id', 'award_document_id')
    def _compute_meta(self):
        for wiz in self:
            loan = wiz.loan_id
            wiz.case_display = loan.case_number if loan else ''
            wiz.loan_display = loan.loan_number if loan else ''

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('default_loan_id'))
        doc = self.env['bharat.loan.award.document'].browse(
            self.env.context.get('default_award_document_id')
        )
        if loan and not vals.get('loan_id'):
            vals['loan_id'] = loan.id
        if doc and not vals.get('award_document_id'):
            vals['award_document_id'] = doc.id
        if doc and not vals.get('award_notes'):
            vals['award_notes'] = doc.award_notes
        return vals

    def action_save(self):
        self.ensure_one()
        if not self.signed_award_pdf:
            raise UserError(_('Please upload the signed award letter PDF.'))
        filename = (self.signed_award_pdf_filename or '').strip()
        if not filename:
            raise UserError(_('Could not read the PDF filename; upload the file again.'))

        doc = self.award_document_id
        if not doc or doc.loan_id != self.loan_id:
            raise UserError(_('Award document does not match this case.'))

        doc.write({
            'award_pdf': self.signed_award_pdf,
            'award_pdf_filename': filename,
            'signed_on': self.signed_on,
            'award_notes': self.award_notes or doc.award_notes,
        })

        when_txt = fields.Datetime.to_string(self.signed_on) if self.signed_on else ''
        pdf_bytes = base64.b64decode(doc.award_pdf)
        self.loan_id.message_post(
            body=_(
                'Signed award letter uploaded: <b>%(file)s</b><br/>Signed on: %(when)s'
            ) % {'file': filename, 'when': when_txt or _('(not set)')},
            attachments=[(filename, pdf_bytes)],
        )
        return {'type': 'ir.actions.act_window_close'}
