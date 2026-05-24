# -*- coding: utf-8 -*-
import base64
import secrets
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError


class BharatLoanNoticeWizard(models.TransientModel):
    _name = 'bharat.loan.notice.wizard'
    _description = 'Send Notice Wizard'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    notice_type = fields.Selection(
        [('notice', 'Notice')],
        required=True,
        default='notice',
    )
    notice_number = fields.Integer(string='Notice #', default=1, required=True)
    template_id = fields.Many2one(
        'bharat.notification.template',
        string='Template',
        domain="[('notice_type', '=', notice_type), ('active', '=', True)]",
    )
    recipient_partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
    )
    subject = fields.Char(required=True)
    body = fields.Text(required=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            be = (loan.borrower_email or '').strip()
            if be:
                Partner = self.env['res.partner']
                rp = Partner.search([('email', '=ilike', be)], limit=1)
                if not rp:
                    rp = Partner.search([('child_ids.email', '=ilike', be)], limit=1)
                if rp:
                    vals.setdefault('recipient_partner_id', rp.id)
        notice_type = self.env.context.get('default_notice_type')
        if notice_type:
            vals.setdefault('notice_type', notice_type)
        notice_number = self.env.context.get('default_notice_number')
        if notice_number:
            vals.setdefault('notice_number', int(notice_number))
        elif loan:
            vals.setdefault('notice_number', (max(loan.notice_line_ids.mapped('notice_number') or [0]) + 1))
        if loan and vals.get('notice_type'):
            template = self.env['bharat.notification.template'].search(
                [('notice_type', '=', vals['notice_type']), ('active', '=', True)],
                limit=1,
            )
            if template:
                subject, body = template.render_for_loan(loan)
                vals.setdefault('template_id', template.id)
                vals.setdefault('subject', subject)
                vals.setdefault('body', body)
        return vals

    @api.onchange('template_id', 'notice_type')
    def _onchange_template_id(self):
        for rec in self:
            if not rec.template_id or not rec.loan_id:
                continue
            subject, body = rec.template_id.render_for_loan(rec.loan_id)
            rec.subject = subject
            rec.body = body

    def action_send(self):
        self.ensure_one()
        if not self.loan_id:
            raise UserError('Loan is required.')
        recipient_email = (self.recipient_partner_id.email or '').strip()
        if not recipient_email:
            raise UserError('Selected recipient has no email; pick a partner with an email or update the contact.')
        recipient_label = self.recipient_partner_id.display_name or recipient_email

        mail_values = {
            'subject': self.subject,
            'body_html': (self.body or '').replace('\n', '<br/>'),
            'email_to': recipient_email,
            'auto_delete': False,
        }
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        pdf_content = False
        pdf_filename = False
        pdf_bytes = None
        token = uuid.uuid4().hex
        otp = '%06d' % secrets.randbelow(1000000)

        line = self.env['bharat.loan.notice.line'].create({
            'loan_id': self.loan_id.id,
            'notice_type': self.notice_type,
            'notice_number': self.notice_number or 1,
            'sent_on': fields.Datetime.now(),
            'sent_by_id': self.env.user.id,
            'recipient_partner_id': self.recipient_partner_id.id,
            'sent_to': recipient_email,
            'subject': self.subject,
            'body_html': (self.body or '').replace('\n', '<br/>'),
            'qr_access_token': token,
            'microsite_otp_code': otp,
        })

        report = self.env.ref(
            'bharatnyay_core.action_report_bharat_notice_line_notice',
            raise_if_not_found=False,
        )
        if report:
            pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=line.ids)
            pdf_content = base64.b64encode(pdf_bytes)
            pdf_filename = (
                'Notice_%s_%s_%s.pdf'
                % (self.notice_number or 1, self.loan_id.loan_number or self.loan_id.id, token[:8])
            )
            line.write({'notice_pdf': pdf_content, 'notice_pdf_filename': pdf_filename})

        self.loan_id._write_stage_by_code('notice')

        post_vals = dict(
            body=(
                f"Notice sent: <b>Notice {self.notice_number or 1}</b>"
                f"<br/>To: {recipient_label} &lt;{recipient_email}&gt;"
                f"<br/>Subject: {self.subject}"
                f"<br/>Borrower microsite OTP (demo): <b>{otp}</b>"
            ),
        )
        if pdf_bytes and pdf_filename:
            post_vals['attachments'] = [(pdf_filename, pdf_bytes)]
        self.loan_id.message_post(**post_vals)
        return {'type': 'ir.actions.act_window_close'}
