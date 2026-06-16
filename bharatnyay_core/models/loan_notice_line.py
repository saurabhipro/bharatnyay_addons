# -*- coding: utf-8 -*-
import base64
import logging
import secrets
import uuid

import werkzeug.urls

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_datetime

_logger = logging.getLogger(__name__)


class BharatLoanNoticeLine(models.Model):
    _name = 'bharat.loan.notice.line'
    _description = 'Loan notice dispatch history'
    _order = 'sent_on desc, id desc'
    _rec_name = 'notice_label'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    loan_number = fields.Char(related='loan_id.loan_number', store=True, readonly=True)
    company_id = fields.Many2one(
        'res.company',
        related='loan_id.company_id',
        store=True,
        readonly=True,
    )
    qr_access_token = fields.Char(
        string='QR token',
        copy=False,
        index=True,
        help='Opaque token embedded in the notice QR code for the borrower microsite.',
    )
    microsite_otp_code = fields.Char(string='Borrower OTP (demo)', copy=False)
    microsite_last_submit_at = fields.Datetime(string='Microsite last submit', copy=False)
    borrower_slot_preference = fields.Char(string='Borrower hearing preference', copy=False)
    notice_microsite_url = fields.Char(string='Microsite URL', compute='_compute_notice_microsite_links')
    notice_microsite_url_encoded = fields.Char(
        string='Microsite URL (encoded)',
        compute='_compute_notice_microsite_links',
    )
    notice_number = fields.Integer(string='Notice #', default=1, index=True)
    notice_label = fields.Char(string='Notice label', compute='_compute_notice_label', store=True)
    notice_type = fields.Selection([('notice', 'Notice')], default='notice', required=True)
    sent_on = fields.Datetime(string='Sent on', default=fields.Datetime.now, required=True)
    sent_by_id = fields.Many2one('res.users', string='Sent by', default=lambda self: self.env.user, required=True)
    recipient_partner_id = fields.Many2one(
        'res.partner',
        string='Sent to (contact)',
        ondelete='set null',
        index=True,
    )
    sent_to = fields.Char(string='Sent to (email)', required=True)
    subject = fields.Char(string='Subject')
    body_html = fields.Html(string='Email body')
    notice_pdf = fields.Binary(string='Notice PDF', attachment=True)
    notice_pdf_filename = fields.Char(string='Notice PDF filename')
    response_pdf = fields.Binary(string='Respondent response PDF', attachment=True)
    response_pdf_filename = fields.Char(string='Response filename')
    response_notes = fields.Text(string='Response notes')
    response_received_on = fields.Datetime(string='Response received on')

    has_pod_tracking = fields.Boolean(
        string='Postal POD tracking',
        compute='_compute_delivery_info',
        store=True,
    )
    postal_dispatch_id = fields.Many2one(
        'bharat.loan.postal.dispatch',
        string='Postal dispatch',
        compute='_compute_delivery_info',
        store=True,
    )
    delivery_status = fields.Char(
        string='Delivery status',
        compute='_compute_delivery_info',
        store=True,
    )
    delivery_status_key = fields.Char(
        compute='_compute_delivery_info',
        store=True,
    )
    delivery_meta = fields.Char(
        string='Delivery details',
        compute='_compute_delivery_info',
        store=True,
    )
    pod = fields.Char(related='postal_dispatch_id.pod', string='POD / tracking no.', readonly=True)
    post_office_status_id = fields.Many2one(
        related='postal_dispatch_id.post_office_status_id',
        string='Post office status',
        readonly=True,
    )
    dispatch_date = fields.Date(related='postal_dispatch_id.dispatch_date', readonly=True)
    delivery_date = fields.Date(related='postal_dispatch_id.delivery_date', readonly=True)
    postal_delivery_card_json = fields.Json(
        string='Postal delivery card',
        compute='_compute_postal_delivery_card_json',
    )

    @api.depends(
        'has_pod_tracking',
        'loan_id',
        'loan_id.milestone_id',
        'loan_id.milestone_id.code',
        'loan_id.is_case_locked',
        'loan_id.postal_dispatch_ids',
        'loan_id.postal_dispatch_ids.pod',
        'loan_id.postal_dispatch_ids.post_office_status_id',
        'loan_id.postal_dispatch_ids.dispatch_date',
        'loan_id.postal_dispatch_ids.delivery_date',
        'loan_id.postal_dispatch_ids.billing_accrued',
        'loan_id.postal_dispatch_ids.post_office_status_id.is_delivered',
        'loan_id.postal_dispatch_ids.post_office_status_id.triggers_billing',
    )
    def _compute_postal_delivery_card_json(self):
        for rec in self:
            if not rec.has_pod_tracking or not rec.loan_id:
                rec.postal_delivery_card_json = {'cards': []}
                continue
            rows = rec.loan_id._postal_delivery_card_rows()
            rec.postal_delivery_card_json = {
                'cards': [row for row in rows if row.get('document_type') == 'notice_1'],
            }

    @api.depends(
        'notice_number',
        'sent_on',
        'loan_id',
        'loan_id.milestone_id',
        'loan_id.postal_dispatch_ids.pod',
        'loan_id.postal_dispatch_ids.post_office_status_id',
        'loan_id.postal_dispatch_ids.dispatch_date',
        'loan_id.postal_dispatch_ids.delivery_date',
        'loan_id.postal_dispatch_ids.billing_accrued',
    )
    def _compute_delivery_info(self):
        for rec in self:
            rec.has_pod_tracking = (rec.notice_number or 0) == 1
            rec.postal_dispatch_id = False
            rec.delivery_status = ''
            rec.delivery_status_key = 'neutral'
            rec.delivery_meta = ''
            loan = rec.loan_id
            if not loan:
                continue
            if rec.notice_number == 1:
                dispatch = loan.postal_dispatch_ids.filtered(
                    lambda d: d.document_type == 'notice_1'
                )[:1]
                rec.postal_dispatch_id = dispatch.id if dispatch else False
                _state, label, meta = loan._postal_delivery_summary(
                    'notice_1',
                    'Notice 1',
                    'notice_1',
                )
                rec.delivery_status = label
                rec.delivery_status_key = _state
                rec.delivery_meta = meta or ''
            else:
                rec.delivery_status = _('Email dispatched') if rec.sent_on else _('Not sent')
                rec.delivery_status_key = 'email' if rec.sent_on else 'neutral'
                if rec.sent_on:
                    rec.delivery_meta = _('Digital notice sent %s') % format_datetime(
                        self.env, rec.sent_on,
                    )

    def action_update_pod(self):
        """Open POD wizard for Notice 1 postal delivery."""
        self.ensure_one()
        if not self.has_pod_tracking:
            raise UserError(_('Postal POD tracking applies to Notice 1 only.'))
        return self.loan_id.action_open_postal_status_wizard('notice_1')

    @api.depends('qr_access_token')
    def _compute_notice_microsite_links(self):
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        for rec in self:
            tok = rec.qr_access_token or ''
            full = '%s/bn/respond/%s' % (base, tok) if tok else ''
            rec.notice_microsite_url = full
            rec.notice_microsite_url_encoded = werkzeug.urls.url_quote(full, safe='') if full else ''

    @api.depends('notice_number')
    def _compute_notice_label(self):
        for rec in self:
            rec.notice_label = 'Notice %s' % (rec.notice_number or 1)

    def _notice_report_xmlid(self):
        """Map notice # to the full legal PDF template on the loan."""
        self.ensure_one()
        mapping = {
            1: 'bharatnyay_core.action_report_bharat_loan_notice',
            2: 'bharatnyay_core.action_report_bharat_loan_reminder_notice',
            3: 'bharatnyay_core.action_report_bharat_loan_final_notice',
        }
        return mapping.get(self.notice_number or 1, 'bharatnyay_core.action_report_bharat_notice_line_notice')

    def _ensure_notice_qr_tokens(self):
        self.ensure_one()
        vals = {}
        if not self.qr_access_token:
            vals['qr_access_token'] = uuid.uuid4().hex
        if not self.microsite_otp_code:
            vals['microsite_otp_code'] = '%06d' % secrets.randbelow(1000000)
        if vals:
            self.write(vals)

    @api.model
    def _backfill_all_missing_notice_pdfs(self, limit=100, loan_ids=None):
        """Render stored PDFs for notice lines that have email history but no attachment."""
        domain = [('notice_pdf', '=', False)]
        if loan_ids:
            domain.append(('loan_id', 'in', loan_ids))
        lines = self.search(domain, limit=limit)
        done = 0
        for line in lines:
            try:
                line._ensure_notice_qr_tokens()
                if line._attach_notice_pdf():
                    done += 1
            except Exception:
                _logger.exception(
                    'Notice PDF backfill failed for notice line %s (loan %s)',
                    line.id,
                    line.loan_id.id,
                )
        return done

    def _web_read_wants_field(self, specification, field_name):
        if not specification:
            return True
        if isinstance(specification, dict):
            return field_name in specification
        if isinstance(specification, (list, tuple)):
            return field_name in specification
        return False

    def web_read(self, specification):
        """Generate deferred notice PDFs when a notice form is opened."""
        if len(self) == 1 and self._web_read_wants_field(specification, 'notice_pdf'):
            if not self.notice_pdf:
                try:
                    self._ensure_notice_qr_tokens()
                    self._attach_notice_pdf()
                except Exception:
                    _logger.exception(
                        'Notice PDF render failed for notice line %s (loan %s)',
                        self.id,
                        self.loan_id.id,
                    )
        return super().web_read(specification)

    def action_regenerate_notice_pdf(self):
        """Manual fallback when the PDF preview is empty."""
        for line in self:
            line._ensure_notice_qr_tokens()
            line._attach_notice_pdf()
        return True

    def _attach_notice_pdf(self):
        """Render and store the notice PDF on this history line."""
        self.ensure_one()
        loan = self.loan_id
        if not loan:
            return False

        report = self.env.ref(self._notice_report_xmlid(), raise_if_not_found=False)
        if not report:
            report = self.env.ref(
                'bharatnyay_core.action_report_bharat_notice_line_notice',
                raise_if_not_found=False,
            )
        if not report:
            _logger.warning('No notice report configured for notice line %s', self.id)
            return False

        res_ids = loan.ids if report.model == 'bharat.loan' else self.ids
        pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=res_ids)
        ref = loan.loan_number or loan.case_number or loan.id
        filename = 'Notice_%s_%s.pdf' % (self.notice_number or 1, ref)
        self.write({
            'notice_pdf': base64.b64encode(pdf_bytes),
            'notice_pdf_filename': filename,
        })
        return True

    def _get_notice_qr_image_data_uri(self, width=120, height=120):
        """Inline QR for notice-line PDFs."""
        self.ensure_one()
        payload = self.notice_microsite_url or self.loan_id._get_reminder_notice_qr_payload()
        return self.env['ir.actions.report'].bharat_qr_to_data_uri(
            payload,
            width=width,
            height=height,
        )

    def action_record_response(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record respondent reply'),
            'res_model': 'bharat.loan.notice.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_notice_line_id': self.id},
        }


