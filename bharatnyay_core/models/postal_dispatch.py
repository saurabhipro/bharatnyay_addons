# -*- coding: utf-8 -*-
from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

POSTAL_DOCUMENT_TYPES = [
    ('notice_1', 'Notice 1'),
    ('interim_order_1', 'Interim Order 1'),
    ('award', 'Award'),
]

POSTAL_DOCUMENT_BILLING_CODE = {
    'notice_1': 'notice_1',
    'interim_order_1': 'interim_order_1',
    'award': 'award',
}

POSTAL_DOCUMENT_MILESTONE_ENTRY = {
    'notice_1': 'notice_1',
    'interim_order_1': 'hearing_1',
    'award': 'award',
}


class BharatLoanPostalDispatch(models.Model):
    _name = 'bharat.loan.postal.dispatch'
    _description = 'Postal dispatch tracking (parallel billing workflow)'
    _order = 'loan_id, document_type, id'

    loan_id = fields.Many2one(
        'bharat.loan',
        string='Case',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='loan_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    loan_number = fields.Char(related='loan_id.loan_number', store=True, readonly=True)
    document_type = fields.Selection(
        POSTAL_DOCUMENT_TYPES,
        string='Document',
        required=True,
        index=True,
    )
    document_label = fields.Char(compute='_compute_document_label', store=True)
    pod = fields.Char(string='POD / tracking no.', index=True)
    dispatch_date = fields.Date(string='Dispatch date')
    delivery_date = fields.Date(string='Delivery date')
    post_office_status_id = fields.Many2one(
        'bharat.post.office.status',
        string='Post office status',
        index=True,
        ondelete='restrict',
    )
    billing_milestone_code = fields.Char(
        string='Billing code',
        compute='_compute_billing_milestone_code',
        store=True,
        readonly=True,
    )
    billing_event_id = fields.Many2one(
        'bharat.loan.billing.event',
        string='Billing event',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    billing_accrued = fields.Boolean(
        string='Charge accrued',
        compute='_compute_billing_accrued',
        store=True,
    )
    notice_line_id = fields.Many2one(
        'bharat.loan.notice.line',
        string='Notice line',
        ondelete='set null',
    )
    award_document_id = fields.Many2one(
        'bharat.loan.award.document',
        string='Award document',
        ondelete='set null',
    )

    _sql_constraints = [
        (
            'loan_document_uniq',
            'unique(loan_id, document_type)',
            'Each case can only have one postal dispatch row per document type.',
        ),
    ]

    @api.depends('document_type')
    def _compute_document_label(self):
        labels = dict(POSTAL_DOCUMENT_TYPES)
        for rec in self:
            rec.document_label = labels.get(rec.document_type, rec.document_type or '')

    @api.depends('document_type')
    def _compute_billing_milestone_code(self):
        for rec in self:
            rec.billing_milestone_code = POSTAL_DOCUMENT_BILLING_CODE.get(
                rec.document_type or '', False
            )

    @api.depends('billing_event_id', 'billing_event_id.state')
    def _compute_billing_accrued(self):
        for rec in self:
            rec.billing_accrued = bool(
                rec.billing_event_id and rec.billing_event_id.state != 'cancelled'
            )

    @api.model
    def _status_from_text(self, status_text):
        text = (status_text or '').strip()
        if not text:
            return self.env['bharat.post.office.status']
        Status = self.env['bharat.post.office.status']
        exact = Status.search([
            '|', ('name', '=ilike', text), ('code', '=ilike', text),
        ], limit=1)
        if exact:
            return exact
        delivered_words = ('deliver', 'received', 'pod', 'complete')
        lower = text.lower()
        if any(w in lower for w in delivered_words):
            return Status.search([('code', '=', 'delivered')], limit=1)
        return Status.search([('code', '=', 'dispatched')], limit=1)

    @api.model
    def ensure_for_loan(self, loan, document_type):
        """Create a dispatch row when a document enters the postal workflow."""
        loan.ensure_one()
        if document_type not in POSTAL_DOCUMENT_BILLING_CODE:
            return self.browse()
        existing = self.search([
            ('loan_id', '=', loan.id),
            ('document_type', '=', document_type),
        ], limit=1)
        if existing:
            return existing
        vals = {
            'loan_id': loan.id,
            'document_type': document_type,
        }
        if document_type == 'notice_1':
            notice = loan.notice_line_ids.filtered(lambda l: l.notice_number == 1)[:1]
            if notice:
                vals['notice_line_id'] = notice.id
        if document_type == 'award':
            award = loan.award_document_ids.filtered(lambda d: d.award_type == 'final')[:1]
            if award:
                vals['award_document_id'] = award.id
        return self.create(vals)

    @api.model
    def ensure_for_milestone_entry(self, loan, milestone_code):
        """Auto-create postal dispatch rows when case workflow reaches key stages."""
        loan.ensure_one()
        doc_type = {
            'notice_1': 'notice_1',
            'hearing_1': 'interim_order_1',
            'award': 'award',
        }.get(milestone_code)
        if doc_type:
            return self.ensure_for_loan(loan, doc_type)
        return self.browse()

    def _apply_post_office_status_side_effects(self):
        Event = self.env['bharat.loan.billing.event'].sudo()
        for rec in self:
            status = rec.post_office_status_id
            if not status:
                continue
            loan = rec.loan_id
            if status.locks_case and not loan.postal_case_locked:
                loan.sudo().write({'postal_case_locked': True})
            if status.triggers_billing and not rec.billing_accrued:
                event = Event.bharat_accrue_for_postal_dispatch(rec)
                if event:
                    rec.billing_event_id = event.id
            if status.is_delivered and rec.delivery_date:
                loan.sudo().write({
                    'deliver_date': rec.delivery_date,
                    'deliver_status': status.name,
                    'post_office_status_id': status.id,
                })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._apply_post_office_status_side_effects()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('post_office_status_id', 'delivery_date', 'pod', 'dispatch_date')):
            self._apply_post_office_status_side_effects()
        return res

    @api.model
    def _backfill_for_existing_loans(self):
        """Create postal dispatch rows for cases already past Notice 1 / Hearing 1 / Award."""
        Milestone = self.env['bharat.loan.milestone'].sudo()
        Milestone._ensure_default_master_milestones()
        seq_map = {m.code: m.sequence for m in Milestone.search([])}
        Loan = self.env['bharat.loan'].sudo()
        for loan in Loan.search([]):
            loan_seq = seq_map.get(loan._milestone_code() or 'commencement', 0)
            if loan_seq >= seq_map.get('notice_1', 999):
                self.ensure_for_loan(loan, 'notice_1')
            if loan_seq >= seq_map.get('hearing_1', 999):
                self.ensure_for_loan(loan, 'interim_order_1')
            if loan_seq >= seq_map.get('award', 999):
                self.ensure_for_loan(loan, 'award')

    @api.model
    def _dashboard_pending_postal_status_domain(self, loan_ids=None):
        """Notice 1 / IO1 dispatched but no billable post-office status yet."""
        domain = [
            ('document_type', 'in', ['notice_1', 'interim_order_1']),
            ('billing_accrued', '=', False),
            '|', ('pod', '!=', False), ('dispatch_date', '!=', False),
            '|', ('post_office_status_id', '=', False),
            ('post_office_status_id.triggers_billing', '=', False),
        ]
        if loan_ids is not None:
            domain.append(('loan_id', 'in', loan_ids or [0]))
        return domain

    @api.model
    def dashboard_pending_postal_status_stats(self, loan_domain=None):
        """KPI: postal dispatches awaiting status update before billing can accrue."""
        Loan = self.env['bharat.loan'].sudo()
        if loan_domain:
            loan_ids = Loan.search(loan_domain).ids
        else:
            loan_ids = None
        domain = self._dashboard_pending_postal_status_domain(loan_ids)
        dispatches = self.sudo().search(domain).filtered(
            lambda d: d.dispatch_date or (d.pod or '').strip()
        )
        notice_count = sum(1 for d in dispatches if d.document_type == 'notice_1')
        io_count = sum(1 for d in dispatches if d.document_type == 'interim_order_1')

        Event = self.env['bharat.loan.billing.event'].sudo()
        estimated = 0.0
        for dispatch in dispatches:
            code = dispatch.billing_milestone_code
            loan = dispatch.loan_id
            if not code or not loan.company_id.partner_id:
                continue
            try:
                product = Event._bharat_billing_product_for_milestone(code)
                estimated += Event._bharat_unit_price_for_partner(
                    product, loan.company_id.partner_id, loan.company_id,
                )
            except Exception:
                continue

        return {
            'count': len(dispatches),
            'notice_1_count': notice_count,
            'interim_order_1_count': io_count,
            'estimated_amount': round(estimated, 2),
            'domain': domain,
        }

    def apply_postal_import_row(self, dispatch_date, delivery_date, status_text):
        """Update from CSV import and run billing / lock side effects."""
        self.ensure_one()
        status = self._status_from_text(status_text)
        vals = {}
        if dispatch_date:
            vals['dispatch_date'] = dispatch_date
        if delivery_date:
            vals['delivery_date'] = delivery_date
        elif dispatch_date and status.is_delivered:
            vals['delivery_date'] = dispatch_date
        if status:
            vals['post_office_status_id'] = status.id
        if vals:
            self.write(vals)
        return status

    @api.model
    def _import_parse_date(self, val):
        """Parse date from Excel cell or text (shared by import wizards)."""
        from datetime import datetime

        from ..tools.xlsx_reader import excel_serial_to_date

        if val in (None, '', False):
            return False
        if hasattr(val, 'year'):
            return val
        parsed = excel_serial_to_date(val)
        if parsed:
            return parsed
        text = str(val).strip()
        if not text:
            return False
        for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return False

    @api.model
    def _import_normalize_document_type(self, value):
        """Map spreadsheet notice/document labels to postal document_type keys."""
        text = str(value or '').strip().lower()
        if not text:
            return False
        aliases = {
            'notice_1': {
                '1', '01', 'n1', 'notice 1', 'notice_1', 'notice1', 'notice one',
            },
            'interim_order_1': {
                'interim order 1', 'interim_order_1', 'io1', 'interim 1',
                'interim one', 'interim order one', 'interim order 1',
            },
            'award': {
                'award', 'final award', 'final', 'award document',
            },
        }
        for doc_type, labels in aliases.items():
            if text in labels:
                return doc_type
        if text.isdigit():
            notice_map = {1: 'notice_1', 2: 'interim_order_1', 3: 'award'}
            mapped = notice_map.get(int(text))
            if mapped:
                return mapped
        return False

    @api.model
    def import_pod_status_row(
        self, loan, document_type, pod, dispatch_date, delivery_date,
        status_text, dry_run=False,
    ):
        """Create/update postal dispatch for a case document from import row."""
        loan.ensure_one()
        if document_type not in dict(POSTAL_DOCUMENT_TYPES):
            raise UserError(_('Unknown document type “%s”.') % document_type)

        dispatch = self.ensure_for_loan(loan, document_type)
        track = (pod or '').strip()
        status_label = (status_text or '').strip()

        if dry_run:
            return dispatch, status_label or '-'

        if track:
            dispatch.pod = track
        dispatch.apply_postal_import_row(dispatch_date, delivery_date, status_text)
        loan.message_post(
            body=_(
                'POD import updated <b>%(doc)s</b> — tracking '
                '<b>%(track)s</b>, status <b>%(status)s</b>.'
            ) % {
                'doc': escape(dispatch.document_label or document_type),
                'track': escape(track or '-'),
                'status': escape(
                    status_text or dispatch.post_office_status_id.name or '-'
                ),
            },
        )
        return dispatch, status_label or dispatch.post_office_status_id.name or '-'
