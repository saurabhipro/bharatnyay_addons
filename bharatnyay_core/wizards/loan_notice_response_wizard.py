# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanNoticeResponseWizard(models.TransientModel):
    _name = 'bharat.loan.notice.response.wizard'
    _description = 'Record respondent notice reply'

    notice_line_id = fields.Many2one(
        'bharat.loan.notice.line',
        required=True,
        readonly=True,
    )
    loan_display = fields.Char(string='Loan', compute='_compute_line_meta', readonly=True)
    notice_label_display = fields.Char(string='Notice', compute='_compute_line_meta', readonly=True)
    subject_display = fields.Char(string='Notice subject', compute='_compute_line_meta', readonly=True)

    response_pdf = fields.Binary(string='Response PDF')
    response_pdf_filename = fields.Char(string='Response PDF filename')
    response_received_on = fields.Datetime(
        string='Response received on',
        required=True,
        default=fields.Datetime.now,
    )
    response_notes = fields.Text(string='Response notes')

    @api.depends('notice_line_id')
    def _compute_line_meta(self):
        for wiz in self:
            line = wiz.notice_line_id
            wiz.loan_display = line.loan_id.display_name if line and line.loan_id else ''
            wiz.notice_label_display = line.notice_label if line else ''
            wiz.subject_display = line.subject if line else ''

    def action_save(self):
        self.ensure_one()
        if not self.notice_line_id:
            raise UserError(_('No notice line.'))
        if not self.response_pdf:
            raise UserError(_("Please upload the respondent's PDF."))
        filename = (self.response_pdf_filename or '').strip()
        if not filename:
            raise UserError(_('Could not read the PDF filename; upload the file again.'))

        self.notice_line_id.write(
            {
                'response_received_on': self.response_received_on,
                'response_notes': self.response_notes or False,
                'response_pdf': self.response_pdf,
                'response_pdf_filename': filename,
            }
        )

        line = self.notice_line_id
        loan = line.loan_id
        label = line.notice_label or _('Notice %s') % (line.notice_number or 1)
        when_txt = ''
        if self.response_received_on:
            when_txt = fields.Datetime.to_string(self.response_received_on)

        loan.message_post(
            body=(
                _('Respondent reply recorded for %(label)s.\nReceived on: %(when)s.')
                % {'label': label, 'when': when_txt or _('(not set)')}
            ),
        )

        return {'type': 'ir.actions.act_window_close'}
