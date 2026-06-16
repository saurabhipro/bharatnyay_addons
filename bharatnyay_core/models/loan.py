# -*- coding: utf-8 -*-
"""Portfolio row aligned to the standard Excel import sheet (one record = one row)."""

from collections import defaultdict
import base64
import logging
import re
import secrets
import uuid
from datetime import datetime, time as dt_time, timedelta

import pytz
import werkzeug.urls
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date, format_datetime
from odoo.osv import expression

_logger = logging.getLogger(__name__)

LOAN_MILESTONE_CODE_SELECTION = [
    ('commencement', 'Commencement'),
    ('notice_1', 'Notice 1'),
    ('notice_2', 'Notice 2'),
    ('notice_3', 'Notice 3'),
    ('hearing_1', 'Hearing 1'),
    ('hearing_2', 'Hearing 2'),
    ('hearing_3', 'Hearing 3'),
    ('award', 'Award'),
]


class BharatLoan(models.Model):
    _name = 'bharat.loan'
    _description = 'Loan portfolio (Excel import)'
    _order = 'loan_number, id'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'loan_number'

    # Fields still writable when case is Award-locked (POD / delivery tracking only).
    _LOCKED_CASE_POSTAL_WRITABLE = frozenset({
        'deliver_date',
        'deliver_status',
        'post_office_status_id',
        'postal_case_locked',
    })

    loan_number = fields.Char(string='Loan Number', required=True, index=True)

    _sql_constraints = [
        (
            'loan_number_uniq',
            'unique(loan_number)',
            'Loan number must be unique. A loan with this number already exists.',
        ),
    ]
    case_number = fields.Char(string='Case No.', copy=False, index=True, readonly=True, tracking=True)
    batch_number = fields.Char(string='Batch', copy=False, index=True, tracking=True)
    customer_name = fields.Char(string='Customer')

    # Keep master links for normalized future usage.
    region_id = fields.Many2one('bharat.region', string='Region', index=True)
    borrower_state_id = fields.Many2one(
        'res.country.state',
        string='State',
        domain="[('country_id.code', '=', 'IN')]",
        index=True,
    )
    branch_id = fields.Many2one('bharat.branch', string='Branch', index=True)
    location_id = fields.Many2one('bharat.loan_location', string='Location')
    product_class_id = fields.Many2one('bharat.product_class', string='Product', index=True)
    writeoff_id = fields.Many2one('bharat.writeoff', string='Write off', index=True)
    law_firm_id = fields.Many2one('bharat.law_firm', string='Law firm')

    # Legacy text columns are kept as primary fields for compatibility with existing DB rows.
    branch = fields.Char(string='Branch')
    borrower_state = fields.Char(string='State')
    region = fields.Char(string='Region')
    location = fields.Char(string='Location')
    product_classification = fields.Char(string='Product classification')
    write_off = fields.Char(string='Write off')
    law_firm_name = fields.Char(string='Law firm name')

    followup_mode = fields.Char(string='Follow-up mode')
    follow_up_mode_alt = fields.Char(string='Follow-up mode (alt)')

    current_pos = fields.Monetary(
        string='Current POS',
        currency_field='currency_id',
    )

    lok_adalat_conciliation = fields.Char(string='Lok Adalat / Conciliation')
    lok_adalat_date = fields.Date(string='Lok Adalat / Conciliation Date')
    lok_adalat_location = fields.Char(string='Lok Adalat / Conciliation Location')
    lok_adalat_location_address = fields.Text(string='Lok Adalat / Conciliation Address')

    company_id = fields.Many2one(
        'res.company',
        string='Lender / company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
        help='Odoo company (NBFC / lender). Used for billing rates, multi-company scope, and lender dashboards.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        compute='_compute_currency_id',
        store=True,
        readonly=True,
    )
    financed_amount = fields.Monetary(string='Financed amount', currency_field='currency_id')
    disbursement_date = fields.Date(string='Date of disbursement')
    product = fields.Char(string='Product')
    case_manager_manual = fields.Boolean(
        string='Case manager manually set',
        default=False,
        copy=False,
    )
    case_manager_id = fields.Many2one(
        'res.users',
        string='Case manager',
        compute='_compute_case_manager_id',
        inverse='_inverse_case_manager_id',
        store=True,
        precompute=True,
        readonly=False,
        index=True,
        tracking=True,
        help='Internal user with Case Manager operational role. Auto-assigned from branch/location scope.',
        domain="[('bharat_role', '=', 'case_manager')]",
    )

    acm_name = fields.Char(string='ACM name')
    complete_assignment = fields.Char(string='Complete assignment')

    legal_fpr = fields.Monetary(string='Legal HPR/FPR', currency_field='currency_id')
    claim_amount = fields.Monetary(string='Claim amount', currency_field='currency_id')
    # Hero KPI strip — compact amounts (no currency symbol) for narrow tiles
    hero_financed_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Financed display',
    )
    hero_pos_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='POS display',
    )
    hero_claim_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Claim display',
    )
    hero_disburse_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Disbursed display',
    )
    notice_hand = fields.Char(string='Notice hand')
    notice_response_pdf = fields.Binary(string='Notice Response PDF', attachment=True)
    notice_response_pdf_filename = fields.Char(string='Notice Response Filename')
    pod = fields.Char(string='POD')
    deliver_date = fields.Date(string='Deliver date')
    deliver_status = fields.Char(string='Deliver status')
    post_office_status_id = fields.Many2one(
        'bharat.post.office.status',
        string='Post office status',
        index=True,
        help='Latest postal delivery status (from dispatch import or manual update).',
    )
    postal_case_locked = fields.Boolean(
        string='Postal lock',
        default=False,
        copy=False,
        help='Case locked after a post office status with “Lock case” (e.g. RRN locked).',
    )
    postal_dispatch_ids = fields.One2many(
        'bharat.loan.postal.dispatch',
        'loan_id',
        string='Postal dispatches',
    )
    postal_delivery_cards_html = fields.Html(
        string='Postal delivery status',
        compute='_compute_postal_delivery_cards_html',
        sanitize=False,
    )
    postal_delivery_cards_json = fields.Json(
        string='Postal delivery cards',
        compute='_compute_postal_delivery_cards_json',
    )

    POSTAL_DELIVERY_DOCUMENTS = (
        {
            'type': 'notice_1',
            'title': 'Notice 1',
            'icon': 'fa-envelope-o',
            'milestone_code': 'notice_1',
        },
        {
            'type': 'interim_order_1',
            'title': 'Interim order 1',
            'icon': 'fa-gavel',
            'milestone_code': 'hearing_1',
        },
        {
            'type': 'award',
            'title': 'Award',
            'icon': 'fa-trophy',
            'milestone_code': 'award',
        },
    )

    STAGE_ICONS = {
        'commencement': '🚀',
        'notice_1': '📩',
        'notice_2': '📩',
        'notice_3': '📩',
        'hearing_1': '🎥',
        'hearing_2': '🎥',
        'hearing_3': '🎥',
        'award': '🏆',
    }
    STAGE_STYLE = {
        'commencement': {'color': '#6366f1', 'icon': 'fa-flag-checkered'},
        'notice_1': {'color': '#0ea5e9', 'icon': 'fa-envelope-o'},
        'notice_2': {'color': '#0284c7', 'icon': 'fa-envelope-open-o'},
        'notice_3': {'color': '#0369a1', 'icon': 'fa-envelope'},
        'hearing_1': {'color': '#8b5cf6', 'icon': 'fa-video-camera'},
        'hearing_2': {'color': '#7c3aed', 'icon': 'fa-gavel'},
        'hearing_3': {'color': '#6d28d9', 'icon': 'fa-gavel'},
        'award': {'color': '#ef4444', 'icon': 'fa-trophy'},
    }

    # ── Dispute playbook / workflow (single milestone master) ────────────
    milestone_id = fields.Many2one(
        'bharat.loan.milestone',
        string='Milestone',
        tracking=True,
        index=True,
        default=lambda self: self.env['bharat.loan.milestone']._default_commencement().id,
    )
    milestone_code = fields.Selection(
        selection=LOAN_MILESTONE_CODE_SELECTION,
        string='Milestone code',
        compute='_compute_milestone_code',
        store=True,
        index=True,
    )
    allowed_milestone_ids = fields.Many2many(
        'bharat.loan.milestone',
        compute='_compute_allowed_milestone_ids',
        string='Allowed milestones',
    )
    next_milestone_label = fields.Char(
        string='Next milestone',
        compute='_compute_next_milestone_label',
    )
    milestone_entered_on = fields.Date(
        string='Stage entered on',
        index=True,
        copy=False,
        help='Date the case entered the current workflow stage (used by auto-advance scheduler).',
    )
    can_move_to_next_stage = fields.Boolean(
        compute='_compute_can_move_to_next_stage',
    )
    arbitration_invoice_count = fields.Integer(
        compute='_compute_arbitration_invoice_count',
    )
    state_is_arbitrator = fields.Boolean(
        string='Stage allows arbitrator assignment',
        compute='_compute_state_is_arbitrator',
        store=True,
    )
    is_case_locked = fields.Boolean(
        string='Case locked (final award)',
        compute='_compute_is_case_locked',
        store=True,
        help='When set (Award milestone), the case form and related records are read-only.',
    )
    state_display = fields.Char(
        string='Stage display',
        compute='_compute_state_display',
    )
    workflow_section = fields.Integer(
        string='Workflow section',
        default=1,
        copy=False,
        help='Arbitration / dispute stage (1–31). Shown as the top timeline.',
    )
    workflow_phase = fields.Char(
        string='Current step label',
        default='Section 1 — Initiation',
        help='Displayed under the timeline (plain-language status).',
        tracking=True,
    )
    notice_line_ids = fields.One2many(
        'bharat.loan.notice.line',
        'loan_id',
        string='Notice history',
    )
    hearing_line_ids = fields.One2many(
        'bharat.loan.hearing.line',
        'loan_id',
        string='Hearing log',
    )
    hearing_minutes_remaining = fields.Integer(
        string='Minutes to next hearing',
        compute='_compute_hearing_minutes_remaining',
        help='Minimum minutes until any scheduled hearing on this case; 0 means a hearing is due now.',
    )
    interim_order_ids = fields.One2many(
        'bharat.loan.interim.order',
        'loan_id',
        string='Interim orders',
    )
    award_document_ids = fields.One2many(
        'bharat.loan.award.document',
        'loan_id',
        string='Award documents',
    )
    billing_event_ids = fields.One2many(
        'bharat.loan.billing.event',
        'loan_id',
        string='Billing charges',
    )

    notice_count = fields.Integer(compute='_compute_case_activity_counts', string='# Notices')
    hearing_log_count = fields.Integer(compute='_compute_case_activity_counts', string='# Hearings')
    interim_order_count = fields.Integer(compute='_compute_case_activity_counts', string='# Interim orders')
    award_document_count = fields.Integer(compute='_compute_case_activity_counts', string='# Awards')
    pending_billing_count = fields.Integer(
        compute='_compute_case_activity_counts',
        string='Unbilled bills',
    )

    borrower_email = fields.Char(string='Borrower email')
    borrower_phone = fields.Char(string='Borrower phone')
    borrower_address = fields.Text(string='Borrower address')

    respondent_name = fields.Char(string='Respondent entity')
    respondent_loan_reference = fields.Char(string='Respondent loan A/C')
    respondent_territory_display = fields.Char(
        string='Respondent geography',
        compute='_compute_respondent_territory_display',
    )

    arbitrator_id = fields.Many2one(
        'res.users',
        string='Arbitrator',
        tracking=True,
        index=True,
        domain=lambda self: self._domain_arbitrator_users(),
        help='Picked from users who have Arbitrator role in User roles.',
    )
    arbitrator_name = fields.Char(string='Arbitrator (text)', help='Legacy / import; synced when Arbitrator user is set.')
    arbitrator_email = fields.Char(string='Arbitrator email')
    arbitrator_handler = fields.Char(string='Arbitrator handler')

    hearing_datetime = fields.Datetime(
        string='Hearing date / time',
        tracking=True,
        help='Stored in UTC; invitations show the viewer’s timezone.',
    )
    hearing_slot_index = fields.Integer(
        string='Hearing slot #',
        compute='_compute_hearing_schedule_header',
    )
    hearing_slot_time_label = fields.Char(
        string='Hearing slot time',
        compute='_compute_hearing_schedule_header',
    )
    hearing_schedule_header = fields.Char(
        string='Hearing schedule',
        compute='_compute_hearing_schedule_header',
    )
    hearing_video_url = fields.Char(
        string='Video meeting URL',
        tracking=True,
        help='Paste Teams, Zoom, Google Meet, or other join link.',
    )
    hearing_notes = fields.Text(
        string='Hearing instructions',
        help='Dial-in numbers, PIN, required documents — included in emailed invitations.',
    )
    hearing_link_type = fields.Selection(
        [
            ('external', 'External conferencing (Teams, Zoom, Meet, …)'),
            ('odoo', 'Odoo case link'),
        ],
        string='Meeting link type',
        default='external',
        tracking=True,
        help='External: paste a third-party video URL. Odoo case link: store a direct link to open this loan '
        'record in the Odoo web app (coordinate live video via Discuss or an external tool separately if needed).',
    )
    calendar_event_id = fields.Many2one(
        'calendar.event',
        string='Odoo meeting',
        copy=False,
        help='Calendar event with Odoo Discuss video call for the current hearing.',
    )
    hearing_invite_user_ids = fields.Many2many(
        'res.users',
        'bharat_loan_hearing_invite_user_rel',
        'loan_id',
        'user_id',
        string='Internal attendees (Odoo users)',
        help='Odoo users added as calendar attendees and emailed the meeting invitation.',
    )
    hearing_external_attendee_ids = fields.Many2many(
        'res.partner',
        'bharat_loan_hearing_ext_attendee_rel',
        'loan_id',
        'partner_id',
        string='External attendees',
        help='Contacts outside Odoo (borrower, counsel, …) added as calendar attendees. '
        'Each must have a valid email to receive the invitation.',
    )
    interim_award_date = fields.Datetime(string='Interim award recorded on', copy=False)
    interim_award_notes = fields.Text(string='Interim award summary', copy=False)
    interim_award_amount = fields.Monetary(
        string='Interim amount (indicative)',
        currency_field='currency_id',
        copy=False,
    )

    ai_classification_hint = fields.Char(string='Classification hint')
    ai_confidence_percent = fields.Float(
        string='Classification confidence %',
        digits=(5, 1),
        help='KPI hint (store 0–100).',
    )
    ai_manual_flags = fields.Integer(
        string='Review flags',
        default=0,
        help='Open issues / anomalies to review.',
    )

    def bharat_invoice_reference_label(self):
        """Loan number + BharatNyay case number for arbitration invoices."""
        self.ensure_one()
        loan_no = (self.loan_number or '').strip()
        bn_case = (self.case_number or '').strip()
        if loan_no and bn_case and loan_no != bn_case:
            return '%s / %s' % (loan_no, bn_case)
        return loan_no or bn_case or self.display_name

    def name_get(self):
        rows = []
        for rec in self:
            ln = rec.loan_number or ''
            cn = rec.case_number or ''
            nm = rec.customer_name or ''
            bits = []
            if ln:
                bits.append(ln)
            if cn and cn != ln:
                bits.append(_('case %s') % cn)
            label = ' — '.join(bits) if bits else (_('Loan %s') % rec.id)
            if nm:
                label = '%s (%s)' % (label, nm)
            rows.append((rec.id, label))
        return rows

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100, order=None):
        """Loan rows have no ``name`` field; search omnibox + M2Os match several references."""
        args = list(args or [])
        if not (name or '').strip():
            # Odoo 18+ BaseModel.name_search does not accept ``order``; keep sort via search when needed.
            return super().name_search(name, args=args, operator=operator, limit=limit)
        or_domain = expression.OR(
            [
                [('loan_number', operator, name)],
                [('case_number', operator, name)],
                [('batch_number', operator, name)],
                [('customer_name', operator, name)],
                [('respondent_loan_reference', operator, name)],
                [('borrower_phone', operator, name)],
                [('borrower_email', operator, name)],
            ]
        )
        domain = expression.AND([args, or_domain])
        records = self.search(domain, limit=limit, order=order)
        return records.name_get()
    dossier_file_count = fields.Integer(
        string='Dossier files',
        default=0,
        help='Rough doc-pack count shown on the KPI strip.',
    )

    @api.depends('company_id', 'company_id.currency_id')
    def _compute_currency_id(self):
        for loan in self:
            if loan.company_id:
                loan.currency_id = loan.company_id.currency_id
            else:
                loan.currency_id = self.env.company.currency_id

    @api.depends('branch_id', 'branch', 'borrower_state_id', 'borrower_state')
    def _compute_respondent_territory_display(self):
        for rec in self:
            parts = []
            if rec.branch_id:
                parts.append(rec.branch_id.name)
            elif rec.branch:
                parts.append(rec.branch)
            if rec.borrower_state_id:
                parts.append(rec.borrower_state_id.name)
            elif rec.borrower_state:
                parts.append(rec.borrower_state)
            rec.respondent_territory_display = ', '.join(p for p in parts if p)

    @api.depends()
    def _compute_allowed_milestone_ids(self):
        milestones = self._milestone_master_ordered()
        for rec in self:
            rec.allowed_milestone_ids = milestones

    def _milestone_code(self):
        self.ensure_one()
        return self.milestone_id.code or self.milestone_code or ''

    def _is_hearing_milestone(self):
        self.ensure_one()
        return (self._milestone_code() or '').startswith('hearing_')

    def _is_notice_milestone(self):
        self.ensure_one()
        return (self._milestone_code() or '').startswith('notice_')

    def _set_milestone(self, milestone):
        self.ensure_one()
        if not milestone:
            raise UserError(_('Unknown workflow milestone.'))
        self.write({
            'milestone_id': milestone.id,
            'milestone_entered_on': fields.Date.context_today(self),
            'workflow_section': milestone.section or 1,
            'workflow_phase': milestone.phase or milestone.name,
        })
        return milestone

    def _set_milestone_by_code(self, code):
        self.ensure_one()
        milestone = self._milestone_by_code(code)
        if not milestone:
            raise UserError(_('Workflow milestone “%s” is not configured.') % code)
        return self._set_milestone(milestone)

    @api.model
    def _milestone_master_ordered(self):
        Milestone = self.env['bharat.loan.milestone']
        if not Milestone.search_count([]):
            Milestone._ensure_default_master_milestones()
        return Milestone.search([('active', '=', True)], order='sequence, id')

    @api.model
    def _milestone_by_code(self, code):
        if not code:
            return self.env['bharat.loan.milestone']
        return self.env['bharat.loan.milestone'].search([('code', '=', code)], limit=1)

    def _next_milestone_record(self):
        self.ensure_one()
        milestones = self._milestone_master_ordered()
        codes = milestones.mapped('code')
        code = self._milestone_code()
        if code not in codes:
            return self.env['bharat.loan.milestone']
        idx = codes.index(code)
        if idx + 1 >= len(milestones):
            return self.env['bharat.loan.milestone']
        return milestones[idx + 1]

    @api.depends('milestone_id', 'milestone_id.code')
    def _compute_milestone_code(self):
        for rec in self:
            rec.milestone_code = rec.milestone_id.code or 'commencement'

    @api.depends('milestone_id', 'milestone_id.code')
    def _compute_next_milestone_label(self):
        for rec in self:
            nxt = rec._next_milestone_record()
            rec.next_milestone_label = nxt.name if nxt else ''

    @api.depends('milestone_id', 'milestone_id.code', 'is_case_locked')
    def _compute_can_move_to_next_stage(self):
        for rec in self:
            rec.can_move_to_next_stage = bool(
                not rec.is_case_locked and rec._next_milestone_record()
            )

    def _compute_arbitration_invoice_count(self):
        Move = self.env['account.move'].sudo()
        Event = self.env['bharat.loan.billing.event'].sudo()
        for rec in self:
            legacy = Move.search_count([
                ('bharat_loan_id', '=', rec.id),
                ('move_type', '=', 'out_invoice'),
                ('bharat_arbitration_invoice', '=', True),
            ])
            consolidated = Event.search_count([
                ('loan_id', '=', rec.id),
                ('state', '=', 'invoiced'),
                ('move_id.move_type', '=', 'out_invoice'),
                ('move_id.bharat_arbitration_invoice', '=', True),
            ])
            rec.arbitration_invoice_count = legacy + consolidated

    def action_open_arbitration_invoices(self):
        self.ensure_one()
        move_ids = self.env['bharat.loan.billing.event'].sudo().search([
            ('loan_id', '=', self.id),
            ('state', '=', 'invoiced'),
            ('move_id', '!=', False),
        ]).mapped('move_id').ids
        legacy_ids = self.env['account.move'].sudo().search([
            ('bharat_loan_id', '=', self.id),
            ('move_type', '=', 'out_invoice'),
            ('bharat_arbitration_invoice', '=', True),
        ]).ids
        all_ids = list(set(move_ids + legacy_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Arbitration invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_ids or [0])],
            'context': {'default_move_type': 'out_invoice'},
        }

    def action_open_unbilled_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Unbilled bills'),
            'res_model': 'bharat.loan.billing.event',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id), ('state', '=', 'pending')],
            'context': {'default_loan_id': self.id, 'create': False},
        }

    def action_open_billing_test_wizard(self):
        """Open test wizard to manually queue unbilled charges (admin)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Accrue unbilled charge (test)'),
            'res_model': 'bharat.loan.billing.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_ids': [(6, 0, self.ids)]},
        }

    def action_open_consolidated_billing_wizard(self):
        """Open consolidated billing wizard with batch pre-filled when possible."""
        batch_names = sorted({b for b in self.mapped('batch_number') if (b or '').strip()})
        batch_number = batch_names[0] if len(batch_names) == 1 else None
        return self.bharat_consolidated_billing_wizard_action(batch_number=batch_number)

    @api.model
    def action_open_consolidated_billing_wizard_from_list(self):
        """List header: open wizard using dashboard batch filter."""
        return self.bharat_consolidated_billing_wizard_action()

    @api.model
    def _bharat_dashboard_batch_config_key(self):
        return 'bharatnyay.dashboard.batch.%s' % self.env.uid

    @api.model
    def bharat_set_dashboard_batch_filter(self, batch_number=False):
        """Remember the portfolio dashboard batch filter for billing wizards."""
        self.check_access('read')
        self.env['ir.config_parameter'].sudo().set_param(
            self._bharat_dashboard_batch_config_key(),
            (batch_number or '').strip(),
        )

    @api.model
    def bharat_get_dashboard_batch_filter(self):
        self.check_access('read')
        return (
            self.env['ir.config_parameter'].sudo().get_param(
                self._bharat_dashboard_batch_config_key()
            ) or ''
        ).strip()

    @api.model
    def bharat_consolidated_billing_wizard_action(self, batch_number=None):
        """Open consolidated invoice wizard with batch defaults when known."""
        Batch = self.env['bharat.loan.batch'].sudo()
        Batch._sync_from_loans()
        ctx = dict(self.env.context)
        batch_number = (
            (batch_number or ctx.get('dashboard_batch_number') or self.bharat_get_dashboard_batch_filter() or '')
            .strip()
        )
        wizard_ctx = {}
        if batch_number and batch_number != '__none__':
            batch = Batch.search([('name', '=', batch_number)], limit=1)
            if batch:
                wizard_ctx['default_batch_ids'] = [(6, 0, batch.ids)]
        wizard_ctx['dashboard_batch_number'] = batch_number or False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create consolidated invoice'),
            'res_model': 'bharat.arbitration.invoice.line.loader.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': wizard_ctx,
        }

    def _resolve_borrower_partner(self):
        """Find a partner for the borrower email when available."""
        self.ensure_one()
        email = (self.borrower_email or '').strip()
        if not email:
            return self.env['res.partner']
        Partner = self.env['res.partner']
        partner = Partner.search([('email', '=ilike', email)], limit=1)
        if not partner:
            partner = Partner.search([('child_ids.email', '=ilike', email)], limit=1)
        return partner

    def _milestone_send_notice_email(self, line):
        """Email the borrower when the user opted in during milestone advance."""
        self.ensure_one()
        line.ensure_one()
        email = (line.sent_to or self.borrower_email or '').strip()
        if not email or email == 'noreply@bharatnyay.local':
            return False
        mail_vals = {
            'subject': line.subject or _('Notice %s') % (line.notice_number or 1),
            'body_html': line.body_html or '',
            'email_to': email,
            'auto_delete': False,
        }
        mail = self.env['mail.mail'].sudo().create(mail_vals)
        if line.notice_pdf and line.notice_pdf_filename:
            self.env['ir.attachment'].sudo().create({
                'name': line.notice_pdf_filename,
                'datas': line.notice_pdf,
                'mimetype': 'application/pdf',
                'res_model': 'mail.mail',
                'res_id': mail.id,
            })
        mail.send()
        return True

    def _milestone_send_notice_sms(self, line):
        """SMS placeholder — logs on the case until an SMS gateway is configured."""
        self.ensure_one()
        line.ensure_one()
        phone = (self.borrower_phone or '').strip()
        if not phone:
            return False
        message = _(
            'Notice %(num)s — loan %(loan)s. OTP: %(otp)s'
        ) % {
            'num': line.notice_number or 1,
            'loan': self.loan_number or self.case_number or self.display_name,
            'otp': line.microsite_otp_code or '—',
        }
        self.message_post(
            body=_('SMS sent to %(phone)s: %(message)s') % {
                'phone': phone,
                'message': message,
            },
        )
        return True

    def _milestone_create_notice_line(self, notice_number):
        """Create a notice history row and render the stage PDF (Notice 1–3 templates)."""
        self.ensure_one()
        email = (self.borrower_email or 'noreply@bharatnyay.local').strip()
        partner = self._resolve_borrower_partner()
        subject = _('Notice %s — %s') % (notice_number, self.loan_number or self.case_number or '')
        body_html = ''
        template = self.env['bharat.notification.template'].search(
            [('notice_type', '=', 'notice'), ('active', '=', True)],
            limit=1,
        )
        if template:
            subject, body = template.render_for_loan(self)
            body_html = (body or '').replace('\n', '<br/>')

        line = self.env['bharat.loan.notice.line'].create({
            'loan_id': self.id,
            'notice_type': 'notice',
            'notice_number': notice_number,
            'sent_on': fields.Datetime.now(),
            'sent_by_id': self.env.user.id,
            'recipient_partner_id': partner.id if partner else False,
            'sent_to': email,
            'subject': subject,
            'body_html': body_html,
            'qr_access_token': uuid.uuid4().hex,
            'microsite_otp_code': '%06d' % secrets.randbelow(1000000),
        })
        if not self.env.context.get('bharat_defer_milestone_pdf'):
            line._attach_notice_pdf()
        if not self.env.context.get('bharat_skip_milestone_email'):
            self._milestone_send_notice_email(line)
        if not self.env.context.get('bharat_skip_milestone_sms'):
            self._milestone_send_notice_sms(line)
        return line

    def _milestone_attach_hearing_pdf(self, hearing_number):
        """Render hearing proceedings PDF and attach to the case chatter."""
        self.ensure_one()
        mapping = {
            1: 'bharatnyay_core.action_report_bharat_loan_hearing_proceedings',
            2: 'bharatnyay_core.action_report_bharat_loan_hearing_proceedings_2',
            3: 'bharatnyay_core.action_report_bharat_loan_hearing_final',
        }
        xmlid = mapping.get(hearing_number)
        if not xmlid:
            return False
        report = self.env.ref(xmlid, raise_if_not_found=False)
        if not report:
            return False
        pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=self.ids)
        ref = self.loan_number or self.case_number or self.id
        filename = 'Hearing_%s_%s.pdf' % (hearing_number, ref)
        self.message_post(
            body=_('Hearing %s proceedings PDF generated.') % hearing_number,
            attachments=[(filename, pdf_bytes)],
        )
        return True

    def _ensure_milestone_id(self):
        """Backfill milestone for legacy rows missing milestone_id."""
        self.ensure_one()
        if self.milestone_id:
            return
        n_notice = len(self.notice_line_ids)
        n_hearing = len(self.hearing_line_ids)
        if n_hearing:
            code = 'hearing_%d' % min(n_hearing, 3)
        elif n_notice:
            code = 'notice_%d' % min(n_notice, 3)
        else:
            code = 'commencement'
        milestone = self._milestone_by_code(code)
        if milestone:
            self._set_milestone(milestone)

    @api.model
    def _bharat_migrate_loans_to_milestone_only(self):
        """Upgrade hook: point every case at Workflow milestones (drop loan stages)."""
        Milestone = self.env['bharat.loan.milestone']
        Milestone._ensure_default_master_milestones()
        code_to_milestone = {m.code: m for m in Milestone.search([])}
        loans = self.with_context(bharat_allow_locked_case_write=True).search([
            ('milestone_id', '=', False),
        ])
        for loan in loans:
            code = (loan.milestone_code or '').strip()
            if not code:
                n_notice = len(loan.notice_line_ids)
                n_hearing = len(loan.hearing_line_ids)
                if n_hearing:
                    code = 'hearing_%d' % min(n_hearing, 3)
                elif n_notice:
                    code = 'notice_%d' % min(n_notice, 3)
                else:
                    code = 'commencement'
            milestone = code_to_milestone.get(code)
            if milestone:
                loan.write({
                    'milestone_id': milestone.id,
                    'workflow_section': milestone.section or 1,
                    'workflow_phase': milestone.phase or milestone.name,
                })
        return True

    @api.model
    def _bharat_backfill_notice_pdfs(self, limit=50):
        """Opt-in: render PDFs for notice lines missing attachments (never run on every upgrade)."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('bharatnyay_core.notice_pdf_backfill_done'):
            return True
        NoticeLine = self.env['bharat.loan.notice.line']
        done = NoticeLine._backfill_all_missing_notice_pdfs(limit=limit)
        if done and not NoticeLine.search_count([('notice_pdf', '=', False)]):
            ICP.set_param('bharatnyay_core.notice_pdf_backfill_done', '1')
        return True

    @api.model
    def _bharat_fixup_milestone_code_field_metadata(self):
        """Repair ir.model.fields after a failed Char migration (Odoo 18 selection unlink bug)."""
        cr = self.env.cr
        cr.execute(
            """
            SELECT id, ttype FROM ir_model_fields
            WHERE model = 'bharat.loan' AND name = 'milestone_code'
            LIMIT 1
            """
        )
        row = cr.fetchone()
        if not row:
            return True
        field_id, ttype = row
        if ttype == 'char':
            cr.execute(
                "DELETE FROM ir_model_fields_selection WHERE field_id = %s",
                (field_id,),
            )
            cr.execute(
                "UPDATE ir_model_fields SET ttype = 'selection' WHERE id = %s",
                (field_id,),
            )
        self._bharat_ensure_milestone_code_selections()
        return True

    @api.model
    def _bharat_ensure_milestone_code_selections(self):
        """Register every milestone code (incl. award) on ir.model.fields.selection."""
        field = self.env['ir.model.fields'].search([
            ('model', '=', 'bharat.loan'),
            ('name', '=', 'milestone_code'),
        ], limit=1)
        if not field:
            return True
        Selection = self.env['ir.model.fields.selection'].sudo()
        existing = set(Selection.search([('field_id', '=', field.id)]).mapped('value'))
        for seq, (code, label) in enumerate(LOAN_MILESTONE_CODE_SELECTION):
            if code in existing:
                continue
            Selection.create({
                'field_id': field.id,
                'value': code,
                'name': label,
                'sequence': seq,
            })
        return True

    @api.model
    def _bharat_run_upgrade_hooks(self):
        """Fast, safe hooks invoked once per module upgrade."""
        for hook_name, hook in (
            ('fixup_milestone_code_metadata', self._bharat_fixup_milestone_code_field_metadata),
            ('cleanup_action_menu', self._bharat_cleanup_action_menu),
            ('migrate_loans_to_milestone_only', self._bharat_migrate_loans_to_milestone_only),
            ('sanitize_case_vault_documents', self.env['bharat.case.vault.batch']._bharat_sanitize_case_vault_documents),
        ):
            try:
                hook()
            except Exception:
                _logger.exception('BharatNyay upgrade hook failed: %s', hook_name)
        return True

    def _milestone_apply_entry_actions(self, milestone):
        self.ensure_one()
        if milestone.auto_assign_case_manager and not self.case_manager_id:
            branch_id = self.branch_id.id if self.branch_id else False
            location_id = self.location_id.id if self.location_id else False
            cm_id = self.env['res.users']._find_case_manager_for_scope(branch_id, location_id)
            if not cm_id:
                branch_name = self.branch_id.name if self.branch_id else _('(no branch)')
                location_name = self.location_id.name if self.location_id else _('(no location)')
                raise UserError(
                    _('No case manager found for branch “%s” / location “%s”. '
                      'Add a case manager under Masters, or widen their branch/location scope.')
                    % (branch_name, location_name)
                )
            self.write({'case_manager_manual': False, 'case_manager_id': cm_id})
        if milestone.auto_assign_arbitrator and not self.arbitrator_id:
            arb_id = self.env['res.users']._find_arbitrator_for_assignment()
            if not arb_id:
                raise UserError(_('No active arbitrator found. Mark at least one user as Arbitrator.'))
            self.write({'arbitrator_id': arb_id})
        if milestone.code.startswith('notice_'):
            notice_number = int(milestone.code.split('_')[1])
            existing = self.notice_line_ids.filtered(lambda l: l.notice_number == notice_number)
            if not existing:
                self._milestone_create_notice_line(notice_number)
        if milestone.code == 'hearing_1' and self.arbitrator_id and not self.hearing_line_ids:
            self._provision_hearing_lines_on_arbitrator_assign()
        if milestone.code == 'award':
            doc = self._get_or_create_final_award_document()
            if not self.env.context.get('bharat_defer_milestone_pdf'):
                doc._attach_draft_award_letter()
        elif not self.env.context.get('bharat_defer_milestone_pdf') and milestone.code.startswith('hearing_'):
            hearing_number = int(milestone.code.split('_')[1])
            self._milestone_attach_hearing_pdf(hearing_number)
        self.env['bharat.loan.postal.dispatch'].ensure_for_milestone_entry(self, milestone.code)

    def _milestone_accrue_billing_event(self, milestone):
        """Queue a pending charge when exiting a billable milestone (consolidated billing)."""
        self.ensure_one()
        if milestone.code == 'commencement':
            return self.env['bharat.loan.billing.event']
        from .loan_milestone import POSTAL_BILLING_MILESTONE_CODES
        if milestone.code in POSTAL_BILLING_MILESTONE_CODES:
            # Accrues from postal POD status (Excel import or Update POD wizard).
            return self.env['bharat.loan.billing.event']
        if not milestone.bill_on_milestone_exit:
            return self.env['bharat.loan.billing.event']
        if milestone.auto_invoice_on_exit:
            return self.env['account.move'].bharat_create_case_milestone_invoice(
                self, milestone.code
            )
        return self.env['bharat.loan.billing.event'].bharat_accrue_for_loan(self, milestone)

    def _advance_one_milestone(self):
        """Move a single case to its next milestone. Returns (next_name, skip_reason)."""
        self.ensure_one()
        self._ensure_milestone_id()

        case_ref = self.case_number or self.loan_number or self.display_name
        if self.is_case_locked:
            return False, _('%(case)s — locked (Award)') % {'case': case_ref}

        current = self.milestone_id or self._milestone_by_code(self._milestone_code())
        if not current:
            return False, _('%(case)s — unknown milestone “%s”') % {
                'case': case_ref,
                's': self._milestone_code() or '?',
            }

        nxt = self._next_milestone_record()
        if not nxt:
            return False, _('%(case)s — already at %(milestone)s') % {
                'case': case_ref,
                'milestone': current.name,
            }

        billing_result = self._milestone_accrue_billing_event(current)
        self._milestone_apply_entry_actions(nxt)
        self._set_milestone(nxt)

        body_parts = [_('Moved to %s') % nxt.name]
        if billing_result._name == 'account.move' and billing_result:
            body_parts.append(
                _('Invoice %s posted.')
                % (billing_result.name or billing_result.display_name)
            )
        elif billing_result._name == 'bharat.loan.billing.event' and billing_result:
            body_parts.append(
                _('Billing queued for %s (batch consolidated invoice).')
                % (billing_result.milestone_label or current.name)
            )
        if nxt.auto_assign_case_manager and self.case_manager_id:
            body_parts.append(_('Case manager: %s') % self.case_manager_id.name)
        if nxt.auto_assign_arbitrator and self.arbitrator_id:
            body_parts.append(_('Arbitrator: %s') % self.arbitrator_id.name)
        self.message_post(body='\n'.join(body_parts))
        return nxt.name, False

    @staticmethod
    def _milestone_action_notification(title, message, notif_type='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            },
        }

    def action_move_to_next_stage(
        self, generate_pdfs=False, send_email=False, send_sms=False,
    ):
        """Advance each selected case by one milestone (bulk-safe, per-case logic)."""
        Run = self.env['bharat.process.run']
        total = len(self)
        track_job = total > 1
        run = Run.browse()
        if track_job:
            run = Run.start(
                'milestone_advance',
                _('Milestone advance — %(n)s case(s)') % {'n': total},
            )
            run.update_progress(0, total, _('Starting…'))
            self.env.cr.commit()

        advanced = []
        skipped = []
        failed = []
        advanced_batches = set()
        advance_ctx = {}
        if not generate_pdfs:
            advance_ctx['bharat_defer_milestone_pdf'] = True
        if not send_email:
            advance_ctx['bharat_skip_milestone_email'] = True
        if not send_sms:
            advance_ctx['bharat_skip_milestone_sms'] = True

        try:
            for idx, rec in enumerate(self, start=1):
                if track_job and run.is_cancelled():
                    break
                try:
                    next_name, skip_reason = rec.with_context(
                        **advance_ctx,
                    )._advance_one_milestone()
                except UserError as exc:
                    case_ref = rec.case_number or rec.loan_number or rec.display_name
                    failed.append('%s — %s' % (case_ref, exc.args[0]))
                    continue
                except Exception as exc:
                    case_ref = rec.case_number or rec.loan_number or rec.display_name
                    failed.append('%s — %s' % (case_ref, exc))
                    _logger.exception('Move to next stage failed for loan %s', rec.id)
                    continue

                case_ref = rec.case_number or rec.loan_number or rec.display_name
                if skip_reason:
                    skipped.append(skip_reason)
                else:
                    advanced.append('%s → %s' % (case_ref, next_name))
                    batch_no = (rec.batch_number or '').strip()
                    if batch_no:
                        advanced_batches.add(batch_no)

                if track_job and idx % 20 == 0:
                    run.update_progress(
                        idx,
                        total,
                        _('Processed %(i)s / %(n)s') % {'i': idx, 'n': total},
                    )
                    self.env.cr.commit()
        except Exception as exc:
            if track_job and run:
                run.fail(str(exc))
                self.env.cr.commit()
            raise

        vault_queued = []
        if advanced_batches:
            vault_queued = self.env['bharat.case.vault.batch'].queue_refresh_for_batches(
                advanced_batches,
            )

        if track_job and run:
            job_lines = []
            if advanced:
                job_lines.append(_('Advanced %(n)s case(s).') % {'n': len(advanced)})
            if skipped:
                job_lines.append(_('Skipped %(n)s case(s).') % {'n': len(skipped)})
            if failed:
                job_lines.append(_('Failed %(n)s case(s).') % {'n': len(failed)})
            if vault_queued:
                job_lines.append(
                    _('Case Vault rebuild queued: %s') % ', '.join(vault_queued)
                )
            if track_job and advance_ctx.get('bharat_defer_milestone_pdf'):
                job_lines.append(
                    _('PDFs deferred — open each notice to generate, or re-run with “Generate PDFs”.')
                )
            if send_email or send_sms:
                extras = []
                if send_email:
                    extras.append(_('email'))
                if send_sms:
                    extras.append(_('SMS'))
                job_lines.append(
                    _('Borrower notifications enabled: %s') % ', '.join(extras)
                )
            if run.is_cancelled():
                run._do_cancel(_('Stopped by user.'))
            elif failed and not advanced:
                run.fail('\n'.join(job_lines) if job_lines else _('No cases were advanced.'))
            else:
                run.update_progress(total, total)
                run.finish('\n'.join(job_lines) if job_lines else _('Completed.'))
            self.env.cr.commit()

        title = _('Move to next stage')
        if len(self) == 1 and advanced:
            if vault_queued:
                self.message_post(
                    body=_(
                        'Case Vault rebuild queued for %(batch)s. '
                        'Batch PDFs for the current milestone(s) will appear '
                        'on the dashboard Case Vault panel when the build finishes.'
                    ) % {'batch': ', '.join(vault_queued)},
                )
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'bharat.loan',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if len(self) == 1 and skipped and not failed:
            return self._milestone_action_notification(title, skipped[0], 'warning')
        if len(self) == 1 and failed:
            raise UserError(failed[0].split(' — ', 1)[-1])

        lines = []
        if advanced:
            lines.append(_('Advanced %(n)s case(s):') % {'n': len(advanced)})
            lines.extend(advanced[:15])
            if len(advanced) > 15:
                lines.append(_('… and %(n)s more') % {'n': len(advanced) - 15})
        if skipped:
            lines.append(_('Skipped %(n)s case(s):') % {'n': len(skipped)})
            lines.extend(skipped[:10])
            if len(skipped) > 10:
                lines.append(_('… and %(n)s more') % {'n': len(skipped) - 10})
        if failed:
            lines.append(_('Failed %(n)s case(s):') % {'n': len(failed)})
            lines.extend(failed[:10])

        if vault_queued:
            lines.append(
                _('Case Vault rebuild queued: %(batch)s — batch PDFs will update in the background.')
                % {'batch': ', '.join(vault_queued)}
            )

        if not advanced:
            msg = '\n'.join(lines) if lines else _('No cases were advanced.')
            return self._milestone_action_notification(title, msg, 'warning')

        notif_type = 'warning' if (skipped or failed) else 'success'
        return self._milestone_action_notification(title, '\n'.join(lines), notif_type)

    @api.model
    def action_dashboard_move_to_next_stage(
        self, region_id=False, state_id=False, batch_number=False,
        generate_pdfs=False, send_email=False, send_sms=False,
    ):
        """Advance all eligible cases in the admin dashboard scope."""
        domain = self._dashboard_apply_scope_filters(
            [], region_id=region_id, state_id=state_id, batch_number=batch_number,
        )
        loans = self.search(domain)
        eligible = loans.filtered(
            lambda l: not l.is_case_locked and l._next_milestone_record()
        )
        if not eligible:
            return self._milestone_action_notification(
                _('Move to next stage'),
                _('No cases in the current filter can be advanced.'),
                'warning',
            )
        return eligible.action_move_to_next_stage(
            generate_pdfs=generate_pdfs,
            send_email=send_email,
            send_sms=send_sms,
        )

    @api.model
    def action_dashboard_mark_pod_done(
        self, region_id=False, state_id=False, batch_number=False,
    ):
        """Mark pending Notice 1 / Hearing 1 / Award POD rows as delivered (accrue charges)."""
        domain = self._dashboard_apply_scope_filters(
            [], region_id=region_id, state_id=state_id, batch_number=batch_number,
        )
        Dispatch = self.env['bharat.loan.postal.dispatch']
        stats = Dispatch.dashboard_pod_markable_stats(domain)
        if not stats['count']:
            return self._milestone_action_notification(
                _('Mark POD delivered'),
                _('No pending POD delivery rows in the current filter.'),
                'warning',
            )
        result = Dispatch.dashboard_mark_pod_done(domain)
        parts = [
            _('Marked %(n)s delivery row(s) as delivered.') % {'n': result['updated']},
        ]
        if result['billed']:
            parts.append(
                _('Accrued %(n)s unbilled charge(s).') % {'n': result['billed']}
            )
        else:
            parts.append(_('No new charges were accrued (already billed or not billable).'))
        return self._milestone_action_notification(
            _('Mark POD delivered'),
            '\n'.join(parts),
            'success' if result['updated'] else 'warning',
        )

    @api.model
    def _bharat_cleanup_action_menu(self):
        """Remove legacy PDF server actions from the loan Action menu (upgrade hook)."""
        loan_model = self.env['ir.model']._get('bharat.loan')
        keep = self.env.ref(
            'bharatnyay_core.action_bharat_loan_move_to_next_stage',
            raise_if_not_found=False,
        )
        keep_ids = {keep.id} if keep else set()

        legacy_xmlids = (
            'bharatnyay_core.action_bharat_loan_bulk_written_statement_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_interim_order_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_hearing_final_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_hearing_proceedings_2_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_hearing_proceedings_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_final_notice_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_reminder_notice_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_commencement_arbitration_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_notice_pdf',
            'bharatnyay_core.action_bharat_loan_bulk_envelope_pdf',
        )
        to_unlink = self.env['ir.actions.server']
        for xid in legacy_xmlids:
            action = self.env.ref(xid, raise_if_not_found=False)
            if action and action.id not in keep_ids:
                to_unlink |= action
        if to_unlink:
            to_unlink.unlink()

        stray_servers = self.env['ir.actions.server'].search([
            ('binding_model_id', '=', loan_model.id),
            ('id', 'not in', list(keep_ids)),
        ])
        if stray_servers:
            stray_servers.write({'binding_model_id': False})

        bound_reports = self.env['ir.actions.report'].search([
            ('binding_model_id', '=', loan_model.id),
        ])
        if bound_reports:
            bound_reports.write({'binding_model_id': False})

        return True

    @api.model
    def _compute_next_batch_number(self):
        """Batch 1 when no loans exist; otherwise max existing batch number + 1."""
        if not self.search_count([]):
            return 'Batch 1'
        loans = self.search_read([], ['batch_number'])
        max_n = 0
        for row in loans:
            bn = (row.get('batch_number') or '').strip()
            mobj = re.match(r'^Batch\s*(\d+)\s*$', bn, re.I)
            if mobj:
                max_n = max(max_n, int(mobj.group(1)))
        return 'Batch %d' % (max_n + 1)

    @api.model
    def _import_batch_cache(self):
        if not hasattr(self.env.cr, '_bharat_import_batch_cache'):
            self.env.cr._bharat_import_batch_cache = {}
        return self.env.cr._bharat_import_batch_cache

    @api.model
    def _get_shared_import_batch_number(self):
        cache = self._import_batch_cache()
        if 'batch' not in cache:
            cache['batch'] = self._compute_next_batch_number()
        return cache['batch']

    @api.depends('milestone_id', 'milestone_id.name', 'milestone_id.code')
    def _compute_state_display(self):
        for rec in self:
            code = rec._milestone_code()
            label = rec.milestone_id.name if rec.milestone_id else 'Unknown'
            ico = self.STAGE_ICONS.get(code, '•')
            rec.state_display = f'{ico} {label}'

    @api.depends('milestone_id', 'milestone_id.is_arbitrator')
    def _compute_state_is_arbitrator(self):
        for rec in self:
            rec.state_is_arbitrator = bool(rec.milestone_id.is_arbitrator)

    @api.depends('milestone_id', 'milestone_id.locks_case', 'milestone_id.code', 'postal_case_locked')
    def _compute_is_case_locked(self):
        for rec in self:
            rec.is_case_locked = bool(
                rec.postal_case_locked
                or rec.milestone_id.locks_case
                or rec._milestone_code() == 'award'
            )

    @staticmethod
    def _format_amount_compact(amount):
        """Format monetary value without symbol: 150000 -> 150K (for narrow hero tiles)."""
        if amount in (None, False):
            return '—'
        try:
            n = float(amount)
        except (TypeError, ValueError):
            return '—'
        if abs(n) < 1e-9:
            return '0'
        sign = '-' if n < 0 else ''
        x = abs(n)

        def tier(div, suffix):
            v = x / div
            if v >= 100:
                t = '%.0f' % v
            elif v >= 10:
                t = ('%.1f' % v).rstrip('0').rstrip('.')
            else:
                t = ('%.1f' % v).rstrip('0').rstrip('.')
            return f'{sign}{t}{suffix}'

        if x >= 1_000_000_000:
            return tier(1_000_000_000, 'B')
        if x >= 1_000_000:
            return tier(1_000_000, 'M')
        if x >= 1000:
            return tier(1000, 'K')
        return f'{sign}{round(x)}'

    @api.depends('financed_amount', 'current_pos', 'claim_amount', 'disbursement_date')
    def _compute_hero_kpi_compact(self):
        for rec in self:
            rec.hero_financed_display = self._format_amount_compact(rec.financed_amount)
            rec.hero_pos_display = self._format_amount_compact(rec.current_pos)
            rec.hero_claim_display = self._format_amount_compact(rec.claim_amount)
            d = rec.disbursement_date
            if not d:
                rec.hero_disburse_display = '—'
            else:
                rec.hero_disburse_display = d.strftime('%d %b %y')

    @api.depends('hearing_datetime')
    def _compute_hearing_schedule_header(self):
        Wiz = self.env['bharat.loan.hearing.schedule.wizard']
        for rec in self:
            rec.hearing_slot_index = 0
            rec.hearing_slot_time_label = ''
            rec.hearing_schedule_header = ''
            if not rec.hearing_datetime:
                continue
            utc_naive = rec.hearing_datetime.replace(second=0, microsecond=0)
            local = fields.Datetime.context_timestamp(rec, rec.hearing_datetime)
            day = local.date()
            idx = Wiz._grid_index_for_datetime_on_day(day, utc_naive)
            rec.hearing_slot_index = idx
            date_label = format_date(rec.env, day)
            if idx:
                wiz = Wiz.new({'loan_id': rec.id, 'scheduler_date': day})
                time_label = wiz._slot_range_label_from_index(day, idx)
                rec.hearing_slot_time_label = time_label
                parts = [date_label, _('Slot %s') % idx]
                if time_label:
                    parts.append(time_label)
                rec.hearing_schedule_header = ' · '.join(parts)
            else:
                rec.hearing_schedule_header = format_datetime(
                    rec.env, rec.hearing_datetime, dt_format='medium',
                )

    @api.model
    def _domain_arbitrator_users(self):
        """Internal users marked as arbitrator on their user record (active)."""
        arbitrators = self.env['res.users'].sudo().search([
            ('bharat_role', '=', 'arbitrator'),
            ('active', '=', True),
            ('share', '=', False),
        ])
        if arbitrators:
            return [('id', 'in', arbitrators.ids)]
        return [('share', '=', False)]

    @staticmethod
    def _apply_arbitrator_user_to_vals(env, vals):
        """Keep legacy text fields aligned when arbitrator_id is set/cleared."""
        if 'arbitrator_id' not in vals:
            return
        arb = vals['arbitrator_id']
        if not arb:
            vals.setdefault('arbitrator_name', False)
            vals.setdefault('arbitrator_email', False)
            return
        user = env['res.users'].browse(arb)
        if user:
            vals['arbitrator_name'] = user.name
            vals['arbitrator_email'] = user.email or ''

    # Hearing log offsets (days) when an arbitrator is assigned.
    _ARBITRATOR_HEARING_OFFSET_DAYS = (1, 10, 30)

    def _sync_arbitrator_appointed_on_assign(self):
        """Provision three hearing log rows when an arbitrator is assigned."""
        for rec in self:
            if not rec.arbitrator_id:
                continue
            rec._provision_hearing_lines_on_arbitrator_assign()

    def _provision_hearing_lines_on_arbitrator_assign(self):
        """Create three hearing log rows (+1, +10, +30 days) if none exist yet."""
        HearingLine = self.env['bharat.loan.hearing.line']
        base = fields.Datetime.now()
        if isinstance(base, str):
            base = fields.Datetime.from_string(base)
        to_create = []
        for rec in self:
            if not rec.arbitrator_id or rec.hearing_line_ids:
                continue
            first_dt = base + timedelta(days=self._ARBITRATOR_HEARING_OFFSET_DAYS[0])
            for days in self._ARBITRATOR_HEARING_OFFSET_DAYS:
                to_create.append({
                    'loan_id': rec.id,
                    'hearing_datetime': base + timedelta(days=days),
                    'link_type': 'external',
                    'created_by_id': self.env.user.id,
                    'status': 'scheduled',
                })
            if not rec.hearing_datetime:
                rec.hearing_datetime = first_dt
        if to_create:
            HearingLine.create(to_create)
        self._check_hearing_countdown_and_promote()

    @api.depends('branch_id', 'location_id', 'branch_id.location_id', 'case_manager_manual')
    def _compute_case_manager_id(self):
        Users = self.env['res.users']
        for rec in self:
            if rec.case_manager_manual:
                continue
            branch_id = rec.branch_id.id if rec.branch_id else False
            location_id = rec.location_id.id if rec.location_id else False
            cm_id = Users._find_case_manager_for_scope(branch_id, location_id)
            rec.case_manager_id = cm_id or False

    def _inverse_case_manager_id(self):
        for rec in self:
            rec.case_manager_manual = bool(rec.case_manager_id)

    @api.model
    def _recompute_auto_case_managers(self):
        """Re-run auto assignment for loans not manually assigned."""
        loans = self.search([
            ('case_manager_manual', '=', False),
            '|', ('branch_id', '!=', False), ('location_id', '!=', False),
        ])
        if loans:
            self.env.add_to_compute(self._fields['case_manager_id'], loans)
        return True

    @api.onchange('arbitrator_id')
    def _onchange_arbitrator_id(self):
        for rec in self:
            if not rec.arbitrator_id:
                continue
            rec.arbitrator_name = rec.arbitrator_id.name
            rec.arbitrator_email = rec.arbitrator_id.email or ''

    @api.constrains('loan_number')
    def _check_loan_number_unique(self):
        for rec in self:
            loan_number = (rec.loan_number or '').strip()
            if not loan_number:
                continue
            duplicate = self.search([
                ('loan_number', '=', loan_number),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _('Loan number "%(number)s" already exists (case %(case)s).')
                    % {
                        'number': loan_number,
                        'case': duplicate.case_number or duplicate.display_name,
                    }
                )

    @api.constrains('workflow_section')
    def _check_workflow_section(self):
        for rec in self:
            sec = rec.workflow_section
            if sec is False or sec is None:
                continue
            if sec < 1 or sec > 31:
                raise ValidationError(_("Workflow section must be between 1 and 31."))

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        for rec in self:
            if not rec.milestone_id:
                continue
            rec.workflow_section = rec.milestone_id.section or 1
            rec.workflow_phase = rec.milestone_id.phase or rec.milestone_id.name

    @api.model
    def _normalize_workflow_values(self, vals):
        if vals.get('milestone_id'):
            milestone = self.env['bharat.loan.milestone'].browse(vals['milestone_id'])
            if milestone:
                vals.setdefault('workflow_section', milestone.section or 1)
                vals.setdefault('workflow_phase', milestone.phase or milestone.name)
            return
        initializing = (
            self.env.context.get('import_file')
            or self.env.context.get('from_import')
            or not self
        )
        if initializing and not vals.get('milestone_id'):
            default = self.env['bharat.loan.milestone']._default_commencement()
            if default:
                vals.setdefault('milestone_id', default.id)
                vals.setdefault('workflow_section', default.section or 1)
                vals.setdefault('workflow_phase', default.phase or default.name)
        if vals.get('milestone_id') and not vals.get('milestone_entered_on'):
            vals.setdefault('milestone_entered_on', fields.Date.context_today(self))

    @api.model
    def _backfill_milestone_entered_on(self):
        """One-time helper: set stage entered date for legacy cases."""
        for loan in self.search([('milestone_entered_on', '=', False)]):
            entered = (
                fields.Date.to_date(loan.create_date)
                if loan.create_date
                else fields.Date.context_today(self)
            )
            loan.milestone_entered_on = entered

    @api.model
    def _cron_auto_advance_workflow_milestones(self):
        """Daily job: move cases to the next stage when stay period elapses."""
        Run = self.env['bharat.process.run']
        run = Run.start(
            'milestone_scheduler',
            _('Workflow auto-advance'),
        )
        try:
            advanced = self._cron_auto_advance_workflow_milestones_impl()
            run.finish(_('Advanced %(n)s case(s).') % {'n': advanced})
            return advanced
        except Exception as exc:
            run.fail(str(exc))
            raise

    @api.model
    def _cron_auto_advance_workflow_milestones_impl(self):
        """Core scheduler logic (logged by ``_cron_auto_advance_workflow_milestones``)."""
        self._backfill_milestone_entered_on()
        today = fields.Date.context_today(self)
        candidates = self.search([
            ('is_case_locked', '=', False),
            ('milestone_entered_on', '!=', False),
            ('milestone_id.stay_days', '>', 0),
        ])
        advanced = 0
        for loan in candidates:
            milestone = loan.milestone_id
            if not milestone or not milestone.stay_days:
                continue
            if not loan._next_milestone_record():
                continue
            deadline = loan.milestone_entered_on + timedelta(days=milestone.stay_days)
            if deadline > today:
                continue
            try:
                next_name, skip_reason = loan._advance_one_milestone()
            except Exception:
                _logger.exception(
                    'Auto-advance failed for loan %s', loan.id,
                )
                continue
            if skip_reason:
                _logger.info(
                    'Auto-advance skipped for %s: %s',
                    loan.loan_number or loan.id,
                    skip_reason,
                )
                continue
            advanced += 1
            _logger.info(
                'Auto-advanced %s to %s after %s days in %s',
                loan.loan_number or loan.id,
                next_name,
                milestone.stay_days,
                milestone.name,
            )
        return advanced

    @api.depends(
        'notice_line_ids',
        'hearing_line_ids',
        'interim_order_ids',
        'award_document_ids',
        'billing_event_ids',
        'billing_event_ids.state',
    )
    def _compute_case_activity_counts(self):
        for rec in self:
            rec.notice_count = len(rec.notice_line_ids)
            rec.hearing_log_count = len(rec.hearing_line_ids)
            rec.interim_order_count = len(rec.interim_order_ids)
            rec.award_document_count = len(rec.award_document_ids)
            rec.pending_billing_count = len(
                rec.billing_event_ids.filtered(lambda e: e.state == 'pending')
            )

    @api.depends('hearing_line_ids.hearing_datetime')
    def _compute_hearing_minutes_remaining(self):
        now = fields.Datetime.now()
        for loan in self:
            mins = []
            for line in loan.hearing_line_ids:
                if not line.hearing_datetime:
                    continue
                delta = line.hearing_datetime - now
                mins.append(max(0, int(delta.total_seconds() // 60)))
            loan.hearing_minutes_remaining = min(mins) if mins else -1

    def _check_hearing_countdown_and_promote(self):
        """Recompute minutes from current time and move to Hearing when min reaches 0."""
        if self.env.context.get('skip_hearing_countdown'):
            return self
        loans = self.with_context(skip_hearing_countdown=True).filtered(
            lambda l: (
                not l.is_case_locked
                and not l._is_hearing_milestone()
                and l.hearing_line_ids
            )
        )
        for loan in loans:
            if loan.hearing_minutes_remaining != 0:
                continue
            loan._promote_to_hearing_stage()

    def _hearing_milestone_for_count(self, hearing_count):
        """Map hearing log row count to hearing_1 / hearing_2 / hearing_3."""
        idx = min(max(hearing_count, 1), 3)
        return self._milestone_by_code('hearing_%d' % idx)

    def _promote_to_hearing_stage(self):
        """Move case to the matching hearing milestone when countdown reaches zero."""
        now = fields.Datetime.now()
        for loan in self.with_context(skip_hearing_countdown=True):
            if loan.is_case_locked or loan._is_hearing_milestone():
                continue
            due_lines = loan.hearing_line_ids.filtered(
                lambda l: l.hearing_datetime and l.hearing_datetime <= now
            )
            if not due_lines:
                continue
            line = due_lines.sorted('hearing_datetime')[-1]
            milestone = loan._hearing_milestone_for_count(len(loan.hearing_line_ids))
            if milestone:
                loan._set_milestone(milestone)
            loan.write({
                'hearing_datetime': line.hearing_datetime,
                'calendar_event_id': line.calendar_event_id.id,
            })

    def web_read(self, specification):
        """Promote to Hearing after load — never during read (breaks web_read cache)."""
        result = super().web_read(specification)
        if not self.env.context.get('skip_hearing_countdown'):
            self._check_hearing_countdown_and_promote()
        return result

    def bharat_arbitration_bill_stage(self):
        """Map case workflow to arbitration billing SKU (product.template stage)."""
        self.ensure_one()
        code = self._milestone_code()
        if self.award_document_ids or code == 'award':
            return 'award'
        if code and code != 'commencement':
            return code
        n_notice = len(self.notice_line_ids)
        n_hear = len(self.hearing_line_ids)
        if n_hear:
            return 'hearing_%d' % min(n_hear, 3)
        if n_notice:
            return 'notice_%d' % min(n_notice, 3)
        return 'commencement'

    def _postal_milestone_sequence(self, milestone_code):
        milestones = self._milestone_master_ordered()
        for milestone in milestones:
            if milestone.code == milestone_code:
                return milestone.sequence
        return 999

    def _postal_delivery_summary(self, document_type, title, milestone_code):
        """Return (state_key, status_label, meta_line) for one postal document."""
        self.ensure_one()
        loan_seq = self._postal_milestone_sequence(self._milestone_code() or 'commencement')
        min_seq = self._postal_milestone_sequence(milestone_code)
        if loan_seq < min_seq:
            return (
                'not_started',
                _('Not started'),
                _('Case has not reached this workflow stage yet'),
            )

        dispatch = self.postal_dispatch_ids.filtered(
            lambda d, dt=document_type: d.document_type == dt
        )[:1]
        if not dispatch:
            return (
                'awaiting',
                _('Awaiting dispatch'),
                _('Postal tracking row will be created at workflow entry'),
            )

        pod = (dispatch.pod or '').strip()
        status = dispatch.post_office_status_id
        meta_bits = []
        if pod:
            meta_bits.append(_('POD %s') % pod)
        if dispatch.dispatch_date:
            meta_bits.append(_('Dispatched %s') % format_date(self.env, dispatch.dispatch_date))
        if dispatch.delivery_date:
            meta_bits.append(_('Delivered %s') % format_date(self.env, dispatch.delivery_date))
        meta = ' · '.join(meta_bits)

        if dispatch.billing_accrued:
            label = status.name if status else _('Delivered')
            return ('billed', label, meta or _('Unbilled charge accrued'))

        if status and status.is_delivered:
            return ('delivered', status.name, meta or _('Delivery confirmed'))

        if status:
            return ('in_progress', status.name, meta or _('Awaiting delivery confirmation'))

        if pod or dispatch.dispatch_date:
            return ('dispatched', _('Dispatched'), meta or _('Awaiting post office status update'))

        return (
            'awaiting',
            _('Awaiting POD'),
            _('Add tracking number or import postal status'),
        )

    def _postal_delivery_card_rows(self):
        """Structured card data for loan form postal delivery widget."""
        self.ensure_one()
        state_labels = {
            'not_started': _('Not started'),
            'awaiting': _('Pending'),
            'dispatched': _('Dispatched'),
            'in_progress': _('In progress'),
            'delivered': _('Delivered'),
            'billed': _('Billed'),
        }
        rows = []
        for spec in self.POSTAL_DELIVERY_DOCUMENTS:
            state, status_label, meta = self._postal_delivery_summary(
                spec['type'],
                spec['title'],
                spec['milestone_code'],
            )
            rows.append({
                'document_type': spec['type'],
                'title': spec['title'],
                'icon': spec['icon'],
                'state': state,
                'badge': state_labels.get(state, status_label),
                'status_label': status_label,
                'meta': meta or '—',
                'clickable': state != 'not_started',
            })
        return rows

    @api.depends(
        'milestone_id',
        'milestone_id.code',
        'is_case_locked',
        'postal_dispatch_ids',
        'postal_dispatch_ids.pod',
        'postal_dispatch_ids.dispatch_date',
        'postal_dispatch_ids.delivery_date',
        'postal_dispatch_ids.post_office_status_id',
        'postal_dispatch_ids.post_office_status_id.is_delivered',
        'postal_dispatch_ids.post_office_status_id.triggers_billing',
        'postal_dispatch_ids.billing_accrued',
    )
    def _compute_postal_delivery_cards_json(self):
        for loan in self:
            loan.postal_delivery_cards_json = {'cards': loan._postal_delivery_card_rows()}

    @api.depends(
        'milestone_id',
        'milestone_id.code',
        'is_case_locked',
        'postal_dispatch_ids',
        'postal_dispatch_ids.pod',
        'postal_dispatch_ids.dispatch_date',
        'postal_dispatch_ids.delivery_date',
        'postal_dispatch_ids.post_office_status_id',
        'postal_dispatch_ids.post_office_status_id.is_delivered',
        'postal_dispatch_ids.post_office_status_id.triggers_billing',
        'postal_dispatch_ids.billing_accrued',
    )
    def _compute_postal_delivery_cards_html(self):
        for loan in self:
            cards = []
            for row in loan._postal_delivery_card_rows():
                doc_type = row['document_type']
                state = row['state']
                clickable = row['clickable']
                tag = 'button' if clickable else 'article'
                click_class = ' bn-postal-card--clickable' if clickable else ''
                click_attrs = (
                    f' type="button" data-document-type="{escape(doc_type)}"'
                    if clickable else ''
                )
                cards.append(
                    Markup(
                        '<%(tag)s class="bn-postal-card bn-postal-card--%(state)s '
                        'bn-postal-card--%(doc_type)s%(click_class)s"%(click_attrs)s>'
                        '<div class="bn-postal-card__head">'
                        '<span class="bn-postal-card__icon"><i class="fa %(icon)s" aria-hidden="true"></i></span>'
                        '<span class="bn-postal-card__title">%(title)s</span>'
                        '<span class="bn-postal-card__badge">%(badge)s</span>'
                        '</div>'
                        '<div class="bn-postal-card__status">%(status)s</div>'
                        '<div class="bn-postal-card__meta">%(meta)s</div>'
                        '</%(tag)s>'
                    ) % {
                        'tag': tag,
                        'state': escape(state),
                        'doc_type': escape(doc_type),
                        'click_class': click_class,
                        'click_attrs': Markup(click_attrs),
                        'icon': escape(row['icon']),
                        'title': escape(row['title']),
                        'badge': escape(row['badge']),
                        'status': escape(row['status_label']),
                        'meta': escape(row['meta']),
                    }
                )
            loan.postal_delivery_cards_html = Markup(
                '<div class="bn-postal-delivery__grid">%s</div>'
            ) % Markup('').join(cards)

    def action_open_postal_status_wizard(self, document_type):
        """Open popup to update POD number and post office status for one document."""
        self.ensure_one()
        valid_types = {spec['type'] for spec in self.POSTAL_DELIVERY_DOCUMENTS}
        if document_type not in valid_types:
            raise UserError(_('Invalid document type.'))
        spec = next(s for s in self.POSTAL_DELIVERY_DOCUMENTS if s['type'] == document_type)
        state, _status_label, _meta = self._postal_delivery_summary(
            document_type,
            spec['title'],
            spec['milestone_code'],
        )
        if state == 'not_started':
            raise UserError(_('This document is not at a stage where postal tracking applies yet.'))

        dispatch = self.env['bharat.loan.postal.dispatch'].ensure_for_loan(
            self, document_type,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Update POD status'),
            'res_model': 'bharat.loan.postal.status.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
                'default_document_type': document_type,
                'default_dispatch_id': dispatch.id,
            },
        }

    def action_open_postal_dispatch(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Postal delivery tracking'),
            'res_model': 'bharat.loan.postal.dispatch',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id, 'search_default_loan_id': self.id},
        }

    def action_open_notice_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Notice history'),
            'res_model': 'bharat.loan.notice.line',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('bharatnyay_core.view_bharat_loan_notice_line_tree').id, 'list'),
                (self.env.ref('bharatnyay_core.view_bharat_loan_notice_line_form').id, 'form'),
            ],
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_hearing_lines(self):
        self.ensure_one()
        self._check_hearing_countdown_and_promote()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hearings'),
            'res_model': 'bharat.loan.hearing.line',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_interim_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interim orders'),
            'res_model': 'bharat.loan.interim.order',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_award_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Awards'),
            'res_model': 'bharat.loan.award.document',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def _get_or_create_final_award_document(self):
        self.ensure_one()
        Award = self.env['bharat.loan.award.document']
        doc = Award.search([
            ('loan_id', '=', self.id),
            ('award_type', '=', 'final'),
        ], order='award_date desc, id desc', limit=1)
        if not doc:
            doc = Award.create({
                'loan_id': self.id,
                'award_type': 'final',
                'award_date': fields.Datetime.now(),
                'award_notes': self.interim_award_notes or False,
                'created_by_id': self.env.user.id,
            })
        return doc

    def action_download_award_letter(self):
        """Generate draft award letter PDF and open download."""
        self.ensure_one()
        if self._milestone_code() != 'award':
            raise UserError(_('Download award letter is only available at the Award milestone.'))
        doc = self._get_or_create_final_award_document()
        doc._attach_draft_award_letter()
        report = self.env.ref(
            'bharatnyay_core.action_report_bharat_loan_award_letter',
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_('Award letter report is not configured.'))
        self.message_post(body=_('Draft award letter generated for download.'))
        return report.report_action(self)

    def action_upload_signed_award(self):
        """Upload the arbitrator-signed award letter PDF."""
        self.ensure_one()
        if self._milestone_code() != 'award':
            raise UserError(_('Upload signed award is only available at the Award milestone.'))
        doc = self._get_or_create_final_award_document()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upload signed award'),
            'res_model': 'bharat.loan.award.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
                'default_award_document_id': doc.id,
            },
        }

    def _action_open_notice_wizard(self, notice_type, notice_number=False):
        self.ensure_one()
        names = {'notice': 'Notice'}
        next_num = notice_number or ((max(self.notice_line_ids.mapped('notice_number') or [0]) + 1) or 1)
        return {
            'type': 'ir.actions.act_window',
            'name': f"Send {names.get(notice_type, 'Notice')}",
            'res_model': 'bharat.loan.notice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'default_notice_type': notice_type,
                'default_notice_number': next_num,
            },
        }

    def action_send_notice_1(self):
        return self._action_open_notice_wizard('notice', notice_number=1)

    def action_send_notice_2(self):
        return self._action_open_notice_wizard('notice', notice_number=2)

    def action_send_notice_3(self):
        return self._action_open_notice_wizard('notice', notice_number=3)

    def action_send_notice(self):
        return self._action_open_notice_wizard('notice')

    def _hearing_build_odoo_case_url(self):
        self.ensure_one()
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        if not base:
            return ''
        cid = self.env.company.id
        act = self.env.ref('bharatnyay_core.action_bharat_loan', raise_if_not_found=False)
        slug = (act.path or '').strip().lower() if act else ''
        if slug:
            # Odoo 17+ web client routes: /odoo/<action.path>/<record_id> (path must NOT contain '.').
            return '%s/odoo/%s/%s?cids=%s' % (base, slug, self.id, cid)
        # Fallback before action.path is upgraded in DB
        return '%s/web#id=%s&model=bharat.loan&view_type=form&cids=%s' % (base, self.id, cid)

    def _get_reminder_notice_qr_payload(self):
        """Raw URL encoded in notice QR codes (microsite or Odoo case link)."""
        self.ensure_one()
        for line in self.notice_line_ids.sorted('sent_on', reverse=True):
            if line.notice_microsite_url:
                return line.notice_microsite_url
        return self._hearing_build_odoo_case_url() or ''

    def _get_reminder_notice_qr_url_encoded(self):
        """URL-encoded payload for legacy /report/barcode links."""
        payload = self._get_reminder_notice_qr_payload()
        return werkzeug.urls.url_quote(payload, safe='') if payload else ''

    def _get_reminder_notice_qr_image_data_uri(self, width=96, height=96):
        """Inline QR for PDF reports (embedded SVG; no /report/barcode fetch)."""
        self.ensure_one()
        return self.env['ir.actions.report'].bharat_qr_to_data_uri(
            self._get_reminder_notice_qr_payload(),
            width=width,
            height=height,
        )

    @staticmethod
    def _hearing_normalize_external_meeting_url(url):
        u = (url or '').strip()
        if not u:
            return ''
        low = u.lower()
        if low.startswith(('http://', 'https://')):
            return u
        if u.startswith('/'):
            return u
        if '://' in u:
            return u
        return 'https://%s' % u

    def action_assign_arbitrator(self):
        self.ensure_one()
        if not self.state_is_arbitrator:
            raise UserError(_('Assign Arbitrator is not available for the current workflow stage.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign Arbitrator'),
            'res_model': 'bharat.loan.assign.arbitrator.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
            },
        }

    def action_move_to_hearing(self):
        """Set workflow milestone to Hearing 1 without opening the schedule wizard."""
        for rec in self:
            if rec._is_hearing_milestone():
                raise UserError(_('This case is already in a hearing milestone.'))
            rec._set_milestone_by_code('hearing_1')
            rec.message_post(body=_('Moved to Hearing 1'))
        return True

    def action_schedule_hearing(self):
        self.ensure_one()
        if self._is_hearing_milestone():
            raise UserError(
                _('This case is already at a hearing milestone. Use “Reschedule hearing” or the Hearing tab.')
            )
        if not self.arbitrator_id:
            raise UserError(
                _('Schedule Hearing requires an arbitrator. Assign one first or move to Hearing 1.')
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Hearing'),
            'res_model': 'bharat.loan.hearing.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def action_reschedule_hearing(self):
        """Move hearing date/time while remaining in a hearing milestone."""
        self.ensure_one()
        if not self._is_hearing_milestone():
            raise UserError(
                _('Use “Schedule Hearing” before hearings begin. Reschedule is only for active hearings.')
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule hearing'),
            'res_model': 'bharat.loan.hearing.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'default_loan_id': self.id,
                'default_hearing_reschedule': True,
            },
        }

    _HEARING_MEETING_MINUTES = 30

    @api.model
    def _hearing_parse_email_list(self, text):
        if not text:
            return []
        return [
            part.strip()
            for part in re.split(r'[,;\s\n]+', str(text).strip())
            if part.strip() and '@' in part
        ]

    def _hearing_ensure_partner_for_email(self, email, name=None):
        """Find or create a lightweight contact so Calendar can email an external guest."""
        self.ensure_one()
        email = (email or '').strip()
        if not email:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([('email', '=ilike', email)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': (name or '').strip() or email,
                'email': email,
                'company_type': 'person',
            })
        return partner

    def _hearing_partners_from_emails(self, emails_text, default_name=None):
        self.ensure_one()
        partners = self.env['res.partner']
        for email in self._hearing_parse_email_list(emails_text):
            partners |= self._hearing_ensure_partner_for_email(email, name=default_name)
        return partners

    def _hearing_default_invite_users(self):
        """Odoo users invited by default: arbitrator + case manager (lender side)."""
        self.ensure_one()
        users = self.env['res.users']
        if self.arbitrator_id:
            users |= self.arbitrator_id
        if self.case_manager_id:
            users |= self.case_manager_id
        return users

    def _hearing_default_external_partners(self):
        """External calendar guests by default: borrower + lender company contact."""
        self.ensure_one()
        partners = self.env['res.partner']
        borrower = self._resolve_borrower_partner()
        if not borrower and (self.borrower_email or '').strip():
            borrower = self._hearing_ensure_partner_for_email(
                self.borrower_email,
                name=self.customer_name or self.borrower_email,
            )
        if borrower:
            partners |= borrower
        company_partner = self.company_id.partner_id
        if company_partner and (company_partner.email or '').strip():
            partners |= company_partner
        return partners

    def _hearing_partner_ids_for_meeting(self, invite_users=None, external_partners=None):
        self.ensure_one()
        partners = self.env.user.partner_id
        if self.arbitrator_id and self.arbitrator_id.partner_id:
            partners |= self.arbitrator_id.partner_id
        users = invite_users if invite_users is not None else self.hearing_invite_user_ids
        partners |= users.mapped('partner_id').filtered(lambda p: p)
        external = (
            external_partners
            if external_partners is not None
            else self.hearing_external_attendee_ids
        )
        partners |= external.filtered('email')
        borrower = self._resolve_borrower_partner()
        if borrower and borrower.email:
            partners |= borrower
        elif (self.borrower_email or '').strip():
            partners |= self._hearing_ensure_partner_for_email(
                self.borrower_email,
                name=self.customer_name or self.borrower_email,
            )
        return partners

    def _hearing_calendar_event(self):
        self.ensure_one()
        if self.calendar_event_id:
            return self.calendar_event_id
        line = self.hearing_line_ids.filtered('calendar_event_id').sorted('hearing_datetime', reverse=True)[:1]
        return line.calendar_event_id

    def _hearing_ensure_calendar_event(self, create_if_missing=True):
        """Return the Discuss calendar event for this hearing, creating one when needed."""
        self.ensure_one()
        event = self._hearing_calendar_event()
        if event:
            return event
        if not create_if_missing or not self.hearing_datetime:
            return self.env['calendar.event']
        invite_users = (
            self.hearing_invite_user_ids
            if self.hearing_invite_user_ids
            else self._hearing_default_invite_users()
        )
        external_partners = (
            self.hearing_external_attendee_ids
            if self.hearing_external_attendee_ids
            else self._hearing_default_external_partners()
        )
        event = self._hearing_upsert_calendar_event(
            self.hearing_datetime,
            invite_users,
            external_partners,
        )
        line = self.hearing_line_ids.filtered(
            lambda l, dt=self.hearing_datetime: l.hearing_datetime == dt
        )[:1]
        if not line:
            line = self.hearing_line_ids.sorted('hearing_datetime', reverse=True)[:1]
        if line and not line.calendar_event_id:
            line.write({
                'calendar_event_id': event.id,
                'link_type': 'odoo',
                'meeting_link': event.videocall_location or '',
            })
        self.write({'calendar_event_id': event.id})
        return event

    def _hearing_upsert_calendar_event(self, start_dt, invite_users=None, external_partners=None):
        """Create or update an Odoo Calendar event with Discuss videocall."""
        self.ensure_one()
        demo = bool(self.env.context.get('bharat_flow_simulation'))
        mail_ctx = {
            'mail_create_nosubscribe': True,
            'mail_create_nolog': True,
            'mail_notrack': True,
            'tracking_disable': True,
        }
        Calendar = self.env['calendar.event'].sudo().with_context(**mail_ctx)
        start = fields.Datetime.to_datetime(start_dt) if isinstance(start_dt, str) else start_dt
        stop = start + timedelta(minutes=self._HEARING_MEETING_MINUTES)
        case_ref = self.case_number or self.loan_number or self.display_name
        if demo:
            partner_ids = []
        else:
            partner_ids = self._hearing_partner_ids_for_meeting(
                invite_users, external_partners,
            ).ids
        vals = {
            'name': _('Hearing — %s') % case_ref,
            'start': fields.Datetime.to_string(start),
            'stop': fields.Datetime.to_string(stop),
            'partner_ids': [(6, 0, partner_ids)],
            'res_model': 'bharat.loan',
            'res_id': self.id,
            'description': _('Arbitration hearing for case %s') % case_ref,
        }
        event = self.calendar_event_id
        if event:
            event.with_context(**mail_ctx).write(vals)
        else:
            event = Calendar.create(vals)
        event._set_discuss_videocall_location()
        return event

    def _hearing_invitation_html(self):
        self.ensure_one()
        when = ''
        if self.hearing_datetime:
            local = fields.Datetime.context_timestamp(self, self.hearing_datetime)
            when = str(local)
        case_ref = self.case_number or self.loan_number or ''
        nm = escape(self.loan_number or '')
        cust = escape(self.customer_name or '')
        parts = [
            '<p>%s</p>' % escape(_('You are invited to the arbitration hearing.')),
            '<p><b>%s</b> %s<br/><b>%s</b> %s / %s</p>'
            % (
                escape(_('Case:')),
                escape(case_ref),
                escape(_('Loan / borrower:')),
                nm,
                cust,
            ),
            '<p><b>%s</b> %s</p>'
            % (
                escape(_('When (reference):')),
                escape(when or _('Not set')),
            ),
        ]
        event = self._hearing_calendar_event()
        url = (event.videocall_location or '').strip() if event else ''
        link_intro = escape(_('Join Odoo meeting (video / conference):'))
        parts.append(
            '<p><b>%s</b><br/><a href="%s">%s</a></p>'
            % (
                link_intro,
                escape(url),
                escape(url) if url else escape(_('(not set)')),
            )
        )
        if self.hearing_notes:
            parts.append(
                '<p><b>%s</b><br/>%s</p>'
                % (
                    escape(_('Instructions:')),
                    escape(self.hearing_notes).replace('\n', '<br/>'),
                )
            )
        return ''.join(parts)

    def action_send_hearing_video_link(self):
        for rec in self:
            if not rec._is_hearing_milestone():
                raise UserError(
                    _('Send video link only when the case is in a hearing milestone.')
                )
            if not rec.hearing_datetime:
                raise UserError(_('Set a hearing date and time before sending invitations.'))
            event = rec._hearing_ensure_calendar_event()
            if not event or not (event.videocall_location or '').strip():
                raise UserError(
                    _('No Odoo meeting is scheduled. Use Schedule or Reschedule hearing first.')
                )

            body_html = rec._hearing_invitation_html()
            case_ref = rec.case_number or rec.loan_number or 'loan'
            subject = _('Hearing link — %s') % case_ref

            Mail = rec.env['mail.mail'].sudo()
            sent_labels = []
            seen_mail = set()

            borrower = (rec.borrower_email or '').strip()
            if borrower:
                key_b = borrower.lower()
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': borrower,
                    'auto_delete': True,
                }).send()
                sent_labels.append(_('borrower'))
                seen_mail.add(key_b)

            arb_mail = ''
            if rec.arbitrator_id and rec.arbitrator_id.email:
                arb_mail = rec.arbitrator_id.email.strip()
            elif rec.arbitrator_email:
                arb_mail = rec.arbitrator_email.strip()
            if arb_mail and arb_mail.lower() not in seen_mail:
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': arb_mail,
                    'auto_delete': True,
                }).send()
                sent_labels.append(_('arbitrator'))
                seen_mail.add(arb_mail.lower())

            for usr in rec.hearing_invite_user_ids:
                em = (usr.email or '').strip() or (usr.partner_id.email or '').strip()
                if not em:
                    continue
                key = em.lower()
                if key in seen_mail:
                    continue
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': em,
                    'auto_delete': True,
                }).send()
                seen_mail.add(key)
                disp = usr.name or usr.login or em
                sent_labels.append(disp)

            if not sent_labels:
                raise UserError(
                    _(
                        'Add a borrower email or arbitrator email, or choose one or more Odoo users '
                        'under “Also email (Odoo users)” on the Hearing tab so invitations have recipients.'
                    )
                )

            rec.message_post(
                body=_('Video meeting invitation sent to: %s') % ', '.join(sent_labels),
            )
        return True

    def action_join_hearing_meeting(self):
        """Join the Odoo Discuss videocall linked to this hearing."""
        self.ensure_one()
        if not self._is_hearing_milestone():
            raise UserError(_('Join online is available during hearing milestones.'))
        if not self.hearing_datetime:
            raise UserError(
                _('Set a hearing date and time before joining. Use Schedule or Reschedule hearing.')
            )
        event = self._hearing_ensure_calendar_event()
        if not event:
            raise UserError(
                _('No Odoo meeting could be created. Use Schedule or Reschedule hearing first.')
            )
        if not (event.videocall_location or '').strip():
            event._set_discuss_videocall_location()
        return event.action_join_video_call()

    def action_pass_interim_award(self):
        self.ensure_one()
        if not self._is_hearing_milestone():
            raise UserError(_('Pass Interim Award is only available during hearing milestones.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pass Interim Award'),
            'res_model': 'bharat.loan.interim.award.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    @api.model
    def _is_data_import(self):
        ctx = self.env.context
        return bool(ctx.get('from_import') or ctx.get('import_file'))

    _IMPORT_GEO_FIELDS = frozenset({
        'region_id', 'state_id', 'borrower_state_id', 'location_id',
    })

    @staticmethod
    def _normalize_master_lookup(name):
        """Strip noise and collapse whitespace for case-insensitive master matching."""
        if not name:
            return ''
        text = str(name).strip()
        text = re.sub(r'\s*\([^)]+\)\s*$', '', text).strip()
        return ' '.join(text.split())

    @api.model
    def _resolve_country_state(self, name):
        """Match imported state text to ``res.country.state`` (India)."""
        value = self._normalize_master_lookup(name)
        if not value:
            return False
        country = self.env.ref('base.in', raise_if_not_found=False)
        domain = [('name', '=ilike', value)]
        if country:
            domain.append(('country_id', '=', country.id))
        return self.env['res.country.state'].search(domain, limit=1)

    @api.model
    def _state_code_for_import(self, name, country):
        """Unique res.country.state code when auto-creating India states from Excel."""
        State = self.env['res.country.state']
        cleaned = re.sub(r'[^A-Za-z0-9]', '', name or '').upper()
        base = (cleaned[:3] or 'ST').ljust(2, 'X')[:3]
        code = base
        seq = 1
        while State.search([('country_id', '=', country.id), ('code', '=', code)], limit=1):
            seq += 1
            code = '%s%02d' % (base[:2], seq)
        return code

    @api.model
    def _ensure_country_state(self, name, region=None):
        """Match or create India state from imported spreadsheet text."""
        state = self._resolve_country_state(name)
        if state:
            if region and self._is_data_import():
                self._align_state_region_for_import(state, region)
            return state
        if not self._is_data_import():
            return False
        value = self._normalize_master_lookup(name)
        if not value:
            return False
        country = self.env.ref('base.in', raise_if_not_found=False)
        if not country:
            return False
        vals = {
            'name': value,
            'country_id': country.id,
            'code': self._state_code_for_import(value, country),
        }
        if region:
            vals['region_id'] = region.id
        return self.env['res.country.state'].sudo().create(vals)

    @api.model
    def _align_state_region_for_import(self, state, region):
        """During import, trust spreadsheet region over stale state master links."""
        if not self._is_data_import() or not state or not region:
            return
        if state.region_id != region:
            state.sudo().write({'region_id': region.id})

    @api.model
    def _ensure_master(self, model_name, name, extra_vals=None):
        """Get-or-create helper for master records from imported text."""
        if not name:
            return False
        value = self._normalize_master_lookup(name)
        if not value:
            return False
        Model = self.env[model_name]
        rec = Model.search([('name', '=ilike', value)], limit=1)
        if rec:
            if extra_vals:
                if self._is_data_import():
                    to_write = {
                        k: v for k, v in extra_vals.items()
                        if v and (k in self._IMPORT_GEO_FIELDS or not rec[k])
                    }
                else:
                    to_write = {k: v for k, v in extra_vals.items() if v and not rec[k]}
                if to_write:
                    rec.write(to_write)
            return rec
        vals = {'name': value}
        if extra_vals:
            vals.update({k: v for k, v in extra_vals.items() if v})
        return Model.create(vals)

    @api.model
    def _coerce_many2one_name_strings(self, vals):
        """Resolve plain name strings mistakenly mapped to *_id columns (import edge cases)."""
        spec = (
            ('region_id', 'bharat.region', 'region'),
            ('borrower_state_id', 'res.country.state', 'borrower_state'),
            ('branch_id', 'bharat.branch', 'branch'),
            ('location_id', 'bharat.loan_location', 'location'),
            ('product_class_id', 'bharat.product_class', 'product_classification'),
            ('writeoff_id', 'bharat.writeoff', 'write_off'),
            ('law_firm_id', 'bharat.law_firm', 'law_firm_name'),
        )
        for m2o_fname, model_name, text_fname in spec:
            raw = vals.get(m2o_fname)
            if not isinstance(raw, str):
                continue
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.isdigit():
                vals[m2o_fname] = int(stripped)
                continue
            if model_name == 'res.country.state':
                region = (
                    self.env['bharat.region'].browse(vals['region_id'])
                    if vals.get('region_id') else False
                )
                rec = self._ensure_country_state(stripped, region=region)
            else:
                rec = self._ensure_master(model_name, stripped)
            if rec:
                vals[m2o_fname] = rec.id
                vals.setdefault(text_fname, stripped)

    @api.model
    def _populate_master_links_from_text(self, vals):
        """During import/create/write, map text columns to Many2one master IDs."""
        region = self._ensure_master('bharat.region', vals.get('region')) if vals.get('region') else False
        if region and not vals.get('region_id'):
            vals['region_id'] = region.id

        state = self._ensure_country_state(vals.get('borrower_state'), region=region) if vals.get('borrower_state') else False
        if state and not vals.get('borrower_state_id'):
            vals['borrower_state_id'] = state.id
        if self._is_data_import() and state and region:
            self._align_state_region_for_import(state, region)
        elif state and state.region_id and not vals.get('region_id'):
            vals['region_id'] = state.region_id.id

        location = self._ensure_master(
            'bharat.loan_location',
            vals.get('location'),
            {
                'region_id': vals.get('region_id'),
                'state_id': vals.get('borrower_state_id'),
            },
        ) if vals.get('location') else False
        if location and not vals.get('location_id'):
            vals['location_id'] = location.id
        if location and location.region_id and not vals.get('region_id'):
            vals['region_id'] = location.region_id.id
        if location and location.state_id and not vals.get('borrower_state_id'):
            vals['borrower_state_id'] = location.state_id.id

        branch = self._ensure_master(
            'bharat.branch',
            vals.get('branch'),
            {
                'region_id': vals.get('region_id'),
                'borrower_state_id': vals.get('borrower_state_id'),
                'location_id': vals.get('location_id'),
            },
        ) if vals.get('branch') else False
        if branch and not vals.get('branch_id'):
            vals['branch_id'] = branch.id
        if branch and branch.region_id and not vals.get('region_id'):
            vals['region_id'] = branch.region_id.id
        if branch and branch.borrower_state_id and not vals.get('borrower_state_id'):
            vals['borrower_state_id'] = branch.borrower_state_id.id
        if branch and branch.location_id and not vals.get('location_id'):
            vals['location_id'] = branch.location_id.id

        if vals.get('product_classification') and not vals.get('product_class_id'):
            pclass = self._ensure_master('bharat.product_class', vals.get('product_classification'))
            if pclass:
                vals['product_class_id'] = pclass.id

        if vals.get('write_off') and not vals.get('writeoff_id'):
            wr = self._ensure_master('bharat.writeoff', vals.get('write_off'))
            if wr:
                vals['writeoff_id'] = wr.id

        if vals.get('law_firm_name') and not vals.get('law_firm_id'):
            firm = self._ensure_master('bharat.law_firm', vals.get('law_firm_name'))
            if firm:
                vals['law_firm_id'] = firm.id

    @api.model
    def _populate_text_from_master_links(self, vals):
        """Keep legacy text columns in sync when import uses Many2one columns."""
        if vals.get('region_id') and not vals.get('region'):
            vals['region'] = self.env['bharat.region'].browse(vals['region_id']).name
        if vals.get('borrower_state_id') and not vals.get('borrower_state'):
            vals['borrower_state'] = self.env['res.country.state'].browse(vals['borrower_state_id']).name
        if vals.get('branch_id') and not vals.get('branch'):
            vals['branch'] = self.env['bharat.branch'].browse(vals['branch_id']).name
        if vals.get('location_id') and not vals.get('location'):
            vals['location'] = self.env['bharat.loan_location'].browse(vals['location_id']).name
        if vals.get('product_class_id') and not vals.get('product_classification'):
            vals['product_classification'] = self.env['bharat.product_class'].browse(vals['product_class_id']).name
        if vals.get('writeoff_id') and not vals.get('write_off'):
            vals['write_off'] = self.env['bharat.writeoff'].browse(vals['writeoff_id']).name
        if vals.get('law_firm_id') and not vals.get('law_firm_name'):
            vals['law_firm_name'] = self.env['bharat.law_firm'].browse(vals['law_firm_id']).name

    @staticmethod
    def _normalize_loan_number_in_vals(vals):
        if 'loan_number' in vals and vals['loan_number'] is not False:
            vals['loan_number'] = (vals['loan_number'] or '').strip()

    @api.model_create_multi
    def create(self, vals_list):
        is_import = bool(self.env.context.get('import_file') or self.env.context.get('from_import'))
        shared_batch_number = False
        if is_import and any(not vals.get('batch_number') for vals in vals_list):
            shared_batch_number = self._get_shared_import_batch_number()

        normalized = []
        for vals in vals_list:
            values = dict(vals)
            self._normalize_loan_number_in_vals(values)
            self._apply_arbitrator_user_to_vals(self.env, values)

            if not values.get('case_number'):
                values['case_number'] = self.env['ir.sequence'].next_by_code('bharat.loan.case.number') or '/'
            if shared_batch_number and not values.get('batch_number'):
                values['batch_number'] = shared_batch_number
            self._normalize_workflow_values(values)
            self._coerce_many2one_name_strings(values)
            self._populate_master_links_from_text(values)
            self._populate_text_from_master_links(values)
            if not values.get('company_id'):
                values['company_id'] = self.env.company.id
            normalized.append(values)
        records = super().create(normalized)
        records.filtered('arbitrator_id')._sync_arbitrator_appointed_on_assign()
        return records

    def write(self, vals):
        locked = self.filtered('is_case_locked')
        if locked and not self.env.context.get('bharat_allow_locked_case_write'):
            disallowed = set(vals) - self._LOCKED_CASE_POSTAL_WRITABLE
            if disallowed:
                raise UserError(
                    _('This case is at Award stage and cannot be modified.')
                )
        values = dict(vals)
        self._normalize_loan_number_in_vals(values)
        self._apply_arbitrator_user_to_vals(self.env, values)
        arbitrator_assigned = bool(values.get('arbitrator_id'))
        self._normalize_workflow_values(values)
        self._coerce_many2one_name_strings(values)
        self._populate_master_links_from_text(values)
        self._populate_text_from_master_links(values)
        res = super().write(values)
        if arbitrator_assigned:
            self._sync_arbitrator_appointed_on_assign()
        return res

    @api.onchange('branch_id')
    def _onchange_branch(self):
        for rec in self:
            branch = rec.branch_id
            if not branch:
                continue
            rec.branch = branch.name
            if branch.location_id:
                rec.location_id = branch.location_id
                rec.location = branch.location_id.name
            if branch.borrower_state_id:
                rec.borrower_state_id = branch.borrower_state_id
                rec.borrower_state = branch.borrower_state_id.name
            elif branch.location_id and branch.location_id.state_id:
                rec.borrower_state_id = branch.location_id.state_id
                rec.borrower_state = branch.location_id.state_id.name
            if branch.region_id:
                rec.region_id = branch.region_id
                rec.region = branch.region_id.name
            elif branch.location_id and branch.location_id.region_id:
                rec.region_id = branch.location_id.region_id
                rec.region = branch.location_id.region_id.name

    @api.onchange('borrower_state_id')
    def _onchange_borrower_state(self):
        for rec in self:
            st = rec.borrower_state_id
            if not st:
                continue
            rec.borrower_state = st.name
            if st.region_id and (not rec.region_id or rec.region_id == st.region_id):
                rec.region_id = st.region_id
                rec.region = st.region_id.name

    @api.onchange('location_id')
    def _onchange_location(self):
        for rec in self:
            loc = rec.location_id
            if not loc:
                if rec.branch_id:
                    rec.branch_id = False
                    rec.branch = False
                continue
            rec.location = loc.name
            if loc.state_id:
                rec.borrower_state_id = loc.state_id
                rec.borrower_state = loc.state_id.name
            if loc.region_id:
                rec.region_id = loc.region_id
                rec.region = loc.region_id.name
            if rec.branch_id and rec.branch_id.location_id != loc:
                rec.branch_id = False
                rec.branch = False

    @api.onchange('region_id', 'product_class_id', 'writeoff_id', 'law_firm_id')
    def _onchange_master_labels(self):
        for rec in self:
            if rec.region_id:
                rec.region = rec.region_id.name
            if rec.product_class_id:
                rec.product_classification = rec.product_class_id.name
            if rec.writeoff_id:
                rec.write_off = rec.writeoff_id.name
            if rec.law_firm_id:
                rec.law_firm_name = rec.law_firm_id.name

    @api.model
    def _dashboard_role_base_domain(self, dashboard_role=None):
        if dashboard_role == 'case_manager':
            return self._case_manager_dashboard_domain()
        if dashboard_role == 'arbitrator':
            return self._arbitrator_dashboard_domain()
        return []

    @api.model
    def _dashboard_apply_scope_filters(
        self, base_domain=None, region_id=False, state_id=False, batch_number=False,
    ):
        """Build loan domain for dashboard scope (region / state / batch)."""
        domain = list(base_domain or [])
        if region_id:
            domain.append(('region_id', '=', int(region_id)))
        if state_id:
            domain.append(('borrower_state_id', '=', int(state_id)))
        if batch_number:
            bn = str(batch_number).strip()
            if bn == '__none__':
                domain.append(('batch_number', 'in', [False, '']))
            elif bn:
                domain.append(('batch_number', '=', bn))
        return domain

    @api.model
    def _dashboard_scope_filters_active(self, region_id=False, state_id=False, batch_number=False):
        return bool(region_id or state_id or batch_number)

    @api.model
    def _dashboard_arbitration_moves_for_loans(self, loans, extra_domain=None):
        """Arbitration invoices linked to a loan set (direct, annexure, or line text)."""
        Move = self.env['account.move'].sudo()
        inv_domain = [
            ('move_type', '=', 'out_invoice'),
            ('bharat_arbitration_invoice', '=', True),
        ]
        if extra_domain:
            inv_domain.extend(extra_domain)
        moves = Move.search(inv_domain)
        if not loans:
            return Move.browse()
        loan_ids = set(loans.ids)
        loan_numbers = {n for n in loans.mapped('loan_number') if n}

        def _matches(move):
            if move.bharat_loan_id and move.bharat_loan_id.id in loan_ids:
                return True
            annexure_ids = move.bharat_annexure_line_ids.mapped('loan_id').ids
            if any(lid in loan_ids for lid in annexure_ids):
                return True
            if loan_numbers:
                blob = ' '.join(move.invoice_line_ids.mapped('name') or [])
                return any(num in blob for num in loan_numbers)
            return False

        return moves.filtered(_matches)

    @api.model
    def _dashboard_batch_payment_breakdown(self, loans, no_batch_label=None):
        """Per-batch case counts by arbitration invoice payment bucket."""
        no_batch_label = no_batch_label or _('No batch')
        by_batch = defaultdict(lambda: {
            'count': 0,
            'paid_cases': 0,
            'unpaid_cases': 0,
            'other_cases': 0,
            'batch_key': '',
        })
        for loan in loans:
            batch_no = (loan.batch_number or '').strip()
            batch_label = batch_no or no_batch_label
            bucket = by_batch[batch_label]
            bucket['count'] += 1
            bucket['batch_key'] = batch_no

            moves = self._dashboard_arbitration_moves_for_loans(loan)
            posted = moves.filtered(lambda m: m.state == 'posted')
            unpaid = posted.filtered(
                lambda m: m.payment_state not in ('paid', 'in_payment')
                and (m.amount_residual or 0) > 0
            )
            paid = posted.filtered(
                lambda m: m.payment_state in ('paid', 'in_payment')
            )
            if unpaid:
                bucket['unpaid_cases'] += 1
            elif paid:
                bucket['paid_cases'] += 1
            else:
                bucket['other_cases'] += 1
        return by_batch

    @api.model
    def _dashboard_batch_volume_payload(self, by_batch_pay, no_batch_label):
        """Serialize batch bar chart rows with paid / unpaid / other segments."""
        batch_items = sorted(
            by_batch_pay.items(),
            key=lambda kv: (kv[0] == no_batch_label, kv[0]),
        )
        batch_volume = []
        for batch_label, agg in batch_items[:20]:
            batch_volume.append({
                'batch': batch_label,
                'batch_key': agg.get('batch_key') or '',
                'count': agg['count'],
                'paid_cases': agg.get('paid_cases', 0),
                'unpaid_cases': agg.get('unpaid_cases', 0),
                'other_cases': agg.get('other_cases', 0),
                'pos_sum': round(agg.get('pos_sum', 0.0), 2),
            })
        overflow = batch_items[20:]
        if overflow:
            batch_volume.append({
                'batch': _('Other'),
                'batch_key': '__other__',
                'count': sum(agg['count'] for _lbl, agg in overflow),
                'paid_cases': sum(agg.get('paid_cases', 0) for _lbl, agg in overflow),
                'unpaid_cases': sum(agg.get('unpaid_cases', 0) for _lbl, agg in overflow),
                'other_cases': sum(agg.get('other_cases', 0) for _lbl, agg in overflow),
                'pos_sum': round(
                    sum(agg.get('pos_sum', 0.0) for _lbl, agg in overflow),
                    2,
                ),
            })
        return batch_volume

    @api.model
    def _dashboard_batch_stage_breakdown(self, loans, no_batch_label=None):
        """Per-batch case counts by workflow milestone."""
        no_batch_label = no_batch_label or _('No batch')
        by_batch = defaultdict(lambda: {
            'count': 0,
            'batch_key': '',
            'stages': defaultdict(int),
        })
        for loan in loans:
            batch_no = (loan.batch_number or '').strip()
            batch_label = batch_no or no_batch_label
            bucket = by_batch[batch_label]
            bucket['count'] += 1
            bucket['batch_key'] = batch_no
            code = (
                loan.milestone_code
                or (loan.milestone_id.code if loan.milestone_id else '')
                or 'commencement'
            )
            bucket['stages'][code] += 1
        return by_batch

    @api.model
    def _dashboard_batch_volume_stage_payload(self, by_batch_stage, no_batch_label):
        """Serialize batch bar chart rows with milestone segments."""
        milestones = self.env['bharat.loan']._milestone_master_ordered()
        stage_legend = []
        for milestone in milestones:
            sty = self.STAGE_STYLE.get(milestone.code, {})
            stage_legend.append({
                'key': milestone.code,
                'label': milestone.name or milestone.code,
                'color': sty.get('color', '#64748b'),
            })

        batch_items = sorted(
            by_batch_stage.items(),
            key=lambda kv: (kv[0] == no_batch_label, kv[0]),
        )
        batches = []
        for batch_label, agg in batch_items[:20]:
            stages = agg.get('stages') or {}
            segments = []
            for leg in stage_legend:
                cnt = stages.get(leg['key'], 0)
                if cnt:
                    segments.append({
                        'key': leg['key'],
                        'label': leg['label'],
                        'count': cnt,
                        'color': leg['color'],
                    })
            batches.append({
                'batch': batch_label,
                'batch_key': agg.get('batch_key') or '',
                'count': agg['count'],
                'segments': segments,
            })
        overflow = batch_items[20:]
        if overflow:
            stage_totals = defaultdict(int)
            total_count = 0
            for _lbl, agg in overflow:
                total_count += agg['count']
                for code, cnt in (agg.get('stages') or {}).items():
                    stage_totals[code] += cnt
            segments = []
            for leg in stage_legend:
                cnt = stage_totals.get(leg['key'], 0)
                if cnt:
                    segments.append({
                        'key': leg['key'],
                        'label': leg['label'],
                        'count': cnt,
                        'color': leg['color'],
                    })
            batches.append({
                'batch': _('Other'),
                'batch_key': '__other__',
                'count': total_count,
                'segments': segments,
            })
        return {
            'batches': batches,
            'legend': stage_legend,
        }

    @api.model
    def get_dashboard_filter_options(
        self, region_id=False, state_id=False, dashboard_role=None,
    ):
        """Dropdown options for portfolio / role dashboards (includes All on the client)."""
        self.check_access('read')
        base = self._dashboard_role_base_domain(dashboard_role)
        domain = self._dashboard_apply_scope_filters(
            base, region_id=region_id, state_id=state_id, batch_number=False,
        )
        loans = self.search(domain)

        regions = self.env['bharat.region'].search([], order='name')
        region_options = [{'id': r.id, 'name': r.name} for r in regions]

        state_domain = [('country_id.code', '=', 'IN')]
        if region_id:
            state_domain.append(('region_id', '=', int(region_id)))
        states = self.env['res.country.state'].search(state_domain, order='name')
        state_options = [
            {
                'id': s.id,
                'name': s.name,
                'region_id': s.region_id.id if s.region_id else False,
            }
            for s in states
        ]

        batch_keys = sorted(
            {(loan.batch_number or '').strip() for loan in loans},
            key=lambda x: (not x, x),
        )
        batch_options = []
        for bn in batch_keys:
            batch_options.append({
                'key': bn or '__none__',
                'label': bn or _('No batch'),
            })

        return {
            'regions': region_options,
            'states': state_options,
            'batches': batch_options,
        }

    @api.model
    def get_dashboard_statistics(
        self, region_id=False, state_id=False, batch_number=False,
        jobs_page=1, jobs_page_size=5, vault_limit=5,
    ):
        """Aggregates for BharatNyay OWL dashboard (JSON-serializable)."""
        self.check_access('read')
        Currency = self.env.company.currency_id
        scope_domain = self._dashboard_apply_scope_filters(
            [], region_id=region_id, state_id=state_id, batch_number=batch_number,
        )
        scope_active = self._dashboard_scope_filters_active(
            region_id, state_id, batch_number,
        )
        rows = self.search_read(
            scope_domain,
            [
                'loan_number',
                'customer_name',
                'milestone_id',
                'milestone_code',
                'branch_id',
                'batch_number',
                'location_id',
                'location',
                'product_class_id',
                'product_classification',
                'product',
                'writeoff_id',
                'current_pos',
                'claim_amount',
                'disbursement_date',
                'create_date',
                'deliver_status',
                'lok_adalat_date',
                'notice_count',
                'award_document_count',
                'arbitrator_id',
            ],
            order='create_date desc',
            limit=100000,
        )

        total = len(rows)
        total_pos = 0.0
        total_claim = 0.0
        borrower_keys = set()
        active_followup = 0
        lok_done = 0

        monthly_created = defaultdict(int)
        monthly_claim = defaultdict(float)
        by_branch = defaultdict(lambda: {'total': 0, 'active_pos': 0, 'pos_sum': 0.0, 'claim_sum': 0.0})
        by_location = defaultdict(lambda: {'total': 0, 'pos_sum': 0.0, 'name': 'Unassigned location'})
        by_product_label = defaultdict(int)
        by_stage = defaultdict(int)
        by_batch = defaultdict(lambda: {'count': 0, 'pos_sum': 0.0})

        pending_dispatch = 0
        cases_no_arbitrator = 0
        pending_award_upload = 0
        batch_keys = set()
        no_batch_label = _('No batch')

        for row in rows:
            pos_val = row.get('current_pos') or 0.0
            try:
                pos_f = float(pos_val)
            except (TypeError, ValueError):
                pos_f = 0.0
            total_pos += pos_f

            claim_val = row.get('claim_amount') or 0.0
            try:
                claim_f = float(claim_val)
            except (TypeError, ValueError):
                claim_f = 0.0
            total_claim += claim_f

            cname = (row.get('customer_name') or '').strip()
            borrower_keys.add((cname or '').lower() or '_blank_')

            if pos_f > 0:
                active_followup += 1
            dsl = row.get('deliver_status')
            dsl_l = dsl.lower().strip() if isinstance(dsl, str) else ''
            delivered = dsl_l in ('delivered', 'yes', 'done', 'y', 'completed')
            if delivered or row.get('lok_adalat_date'):
                lok_done += 1

            if (row.get('notice_count') or 0) > 0 and not delivered and not row.get('lok_adalat_date'):
                pending_dispatch += 1

            stage_key = row.get('milestone_code') or ''
            if (
                stage_key == 'notice_3'
                and not row.get('arbitrator_id')
            ):
                cases_no_arbitrator += 1
            if stage_key == 'award' and not (row.get('award_document_count') or 0):
                pending_award_upload += 1

            if stage_key:
                by_stage[stage_key] += 1

            cdate = row.get('create_date')
            bucket = None
            if hasattr(cdate, 'strftime'):
                bucket = cdate.strftime('%Y-%m')
            elif isinstance(cdate, str) and len(cdate) >= 7:
                bucket = cdate[:7]
            if bucket:
                monthly_created[bucket] += 1
                monthly_claim[bucket] += claim_f

            bik = row.get('branch_id')
            if bik:
                bid, bname = bik[0], bik[1]
            else:
                bid, bname = None, 'Unassigned branch'
            bkey = bid if bid is not None else -1
            by_branch[bkey]['total'] += 1
            by_branch[bkey]['branch_name'] = bname
            by_branch[bkey]['pos_sum'] += pos_f
            by_branch[bkey]['claim_sum'] += claim_f
            if pos_f > 0:
                by_branch[bkey]['active_pos'] += 1

            batch_no = (row.get('batch_number') or '').strip()
            batch_label = batch_no or no_batch_label
            by_batch[batch_label]['count'] += 1
            by_batch[batch_label]['pos_sum'] += pos_f
            by_batch[batch_label]['batch_key'] = batch_no
            if batch_no:
                batch_keys.add(batch_no)

            pcid = row.get('product_class_id')
            pcl = pcid[1] if pcid else None
            if not pcl:
                pcl = row.get('product_classification') or row.get('product') or 'Unclassified'
            by_product_label[pcl] += 1

            lok = row.get('location_id')
            if lok:
                lid, lname = lok[0], lok[1]
            else:
                lid = -1
                lname = (row.get('location') or '').strip() or 'Unassigned location'
            by_location[lid]['total'] += 1
            by_location[lid]['name'] = lname
            by_location[lid]['pos_sum'] += pos_f

        uniq_borrowers = len(borrower_keys)

        month_keys = sorted(set(monthly_created.keys()) | set(monthly_claim.keys()))[-18:]
        monthly_series = [
            {
                'period': mk,
                'count': monthly_created.get(mk, 0),
                'claim_sum': round(monthly_claim.get(mk, 0.0), 2),
            }
            for mk in month_keys
        ]

        scoped_loans = self.search(scope_domain)
        loan_ids = scoped_loans.ids
        movable_cases = len(scoped_loans.filtered(
            lambda l: not l.is_case_locked and l._next_milestone_record()
        ))
        running_jobs = self.env['bharat.process.run'].search_count([
            ('state', 'in', ('queued', 'running')),
        ])
        total_case_managers = self.env['res.users'].sudo().search_count([
            ('share', '=', False),
            ('bharat_role', '=', 'case_manager'),
            ('active', '=', True),
        ])
        total_arbitrators = self.env['res.users'].sudo().search_count([
            ('share', '=', False),
            ('bharat_role', '=', 'arbitrator'),
            ('active', '=', True),
        ])
        batch_pay = self._dashboard_batch_payment_breakdown(
            scoped_loans, no_batch_label=no_batch_label,
        )
        for batch_label, agg in by_batch.items():
            if batch_label in batch_pay:
                batch_pay[batch_label]['pos_sum'] = agg.get('pos_sum', 0.0)
            else:
                batch_pay[batch_label] = {
                    'count': agg['count'],
                    'batch_key': agg.get('batch_key') or '',
                    'pos_sum': agg.get('pos_sum', 0.0),
                    'paid_cases': 0,
                    'unpaid_cases': 0,
                    'other_cases': agg['count'],
                }
        batch_volume = self._dashboard_batch_volume_payload(batch_pay, no_batch_label)
        batch_stage = self._dashboard_batch_stage_breakdown(
            scoped_loans, no_batch_label=no_batch_label,
        )
        batch_volume_stages = self._dashboard_batch_volume_stage_payload(
            batch_stage, no_batch_label,
        )

        palette = ('#6366f1', '#06b6d4', '#8b5cf6', '#22c55e', '#eab308',
                   '#ef4444', '#f97316', '#64748b', '#14b8a6', '#a855f7')
        prod_items = sorted(by_product_label.items(), key=lambda x: -x[1])
        denom = sum(by_product_label.values()) or 1
        pie = []
        for i, (label, cnt) in enumerate(prod_items[:10]):
            pie.append({
                'label': label,
                'count': cnt,
                'percent': round(100.0 * cnt / denom, 2),
                'color': palette[i % len(palette)],
            })
        other = sum(c for _lbl, c in prod_items[10:])
        if other:
            pie.append({
                'label': 'Other',
                'count': other,
                'percent': round(100.0 * other / denom, 2),
                'color': '#94a3b8',
            })

        branches_sorted = sorted(
            by_branch.items(),
            key=lambda kv: kv[1]['total'],
            reverse=True,
        )[:16]

        entity_cards = []
        for _bid, agg in branches_sorted:
            t = agg['total']
            a = agg['active_pos']
            entity_cards.append({
                'title': agg.get('branch_name') or 'Branch',
                'subtitle': '',
                'total': t,
                'active_exposure': a,
                'settled_hint': max(0, t - a),
                'pos_amount': agg['pos_sum'],
                'claim_amount': agg['claim_sum'],
            })

        branch_items = sorted(by_branch.items(), key=lambda kv: kv[1]['total'], reverse=True)
        branch_denom = sum(v['total'] for _k, v in branch_items) or 1
        branch_mix = []
        for i, (bid, agg) in enumerate(branch_items[:12]):
            cnt = agg['total']
            color = palette[i % len(palette)]
            pct = round(100.0 * cnt / branch_denom, 2)
            label = agg.get('branch_name') or 'Unassigned branch'
            branch_mix.append({
                'id': bid,
                'label': label,
                'count': cnt,
                'percent': pct,
                'color': color,
            })
        branch_other = sum(v['total'] for _k, v in branch_items[12:])
        if branch_other:
            branch_mix.append({
                'label': 'Other',
                'count': branch_other,
                'percent': round(100.0 * branch_other / branch_denom, 2),
                'color': '#94a3b8',
            })

        loc_items = sorted(by_location.items(), key=lambda kv: kv[1]['total'], reverse=True)
        loc_denom = sum(v['total'] for _k, v in loc_items) or 1
        location_mix = []
        for i, (lid, agg) in enumerate(loc_items[:12]):
            cnt = agg['total']
            color = palette[i % len(palette)]
            pct = round(100.0 * cnt / loc_denom, 2)
            location_mix.append({
                'id': lid,
                'label': agg['name'],
                'count': cnt,
                'percent': pct,
                'color': color,
            })
        loc_other = sum(v['total'] for _k, v in loc_items[12:])
        if loc_other:
            location_mix.append({
                'label': 'Other',
                'count': loc_other,
                'percent': round(100.0 * loc_other / loc_denom, 2),
                'color': '#94a3b8',
            })

        if scope_active:
            posted_arb = self._dashboard_arbitration_moves_for_loans(
                scoped_loans, [('state', '=', 'posted')],
            )
            draft_moves = self._dashboard_arbitration_moves_for_loans(
                scoped_loans, [('state', '=', 'draft')],
            )
        else:
            Move = self.env['account.move'].sudo()
            arb_inv_domain = [
                ('move_type', '=', 'out_invoice'),
                ('bharat_arbitration_invoice', '=', True),
            ]
            posted_arb = Move.search(arb_inv_domain + [('state', '=', 'posted')])
            draft_moves = Move.search(arb_inv_domain + [('state', '=', 'draft')])

        paid_moves = posted_arb.filtered(
            lambda m: m.payment_state in ('paid', 'in_payment')
        )
        unpaid_moves = posted_arb.filtered(
            lambda m: m.payment_state not in ('paid', 'in_payment')
            and (m.amount_residual or 0) > 0
        )
        paid_invoice_count = len(paid_moves)
        unpaid_invoice_count = len(unpaid_moves)
        total_invoices = len(posted_arb) + len(draft_moves)
        paid_invoice_amount = round(
            sum((m.amount_total or 0) - (m.amount_residual or 0) for m in paid_moves),
            2,
        )
        unpaid_invoice_amount = round(sum(unpaid_moves.mapped('amount_residual')), 2)
        total_invoice_amount = round(
            sum(posted_arb.mapped('amount_total')) + sum(draft_moves.mapped('amount_total')),
            2,
        )
        draft_invoices_count = len(draft_moves)

        pending_billing_domain = [('state', '=', 'pending')]
        if scope_active:
            pending_billing_domain.append(('loan_id', 'in', loan_ids or [0]))
        unbilled_charges_pipeline = self.env[
            'bharat.loan.billing.event'
        ].dashboard_pending_charges_pipeline(loan_ids if scope_active else None)
        unbilled_cases = unbilled_charges_pipeline['total']['cases']
        pending_billing_charges = unbilled_charges_pipeline['total']['count']
        pending_billing_amount = unbilled_charges_pipeline['total']['amount']

        stage_cards, _stage_card_total = self._bucket_cards_from_loans(
            scoped_loans, base_domain=scope_domain,
        )

        pos_ratio = round(100 * active_followup / total, 1) if total else 0.0

        tzname = self.env.user.tz or 'UTC'
        tz = pytz.timezone(tzname)
        today = fields.Date.context_today(self)
        start_local = tz.localize(datetime.combine(today, dt_time.min))
        end_local = tz.localize(datetime.combine(today, dt_time.max))
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        start_s = fields.Datetime.to_string(start_utc)
        end_s = fields.Datetime.to_string(end_utc)

        hearing_domain = [
            ('hearing_datetime', '>=', start_s),
            ('hearing_datetime', '<=', end_s),
        ]
        if scope_active:
            hearing_domain.append(('loan_id', 'in', loan_ids or [0]))
        hearings_today = self.env['bharat.loan.hearing.line'].sudo().search_count(
            hearing_domain,
        )
        draft_invoices = draft_invoices_count
        activities_open = self.env['mail.activity'].sudo().search_count([
            ('res_model', '=', 'bharat.loan'),
            ('date_deadline', '<=', fields.Date.context_today(self)),
        ])

        wf_denom = total or 1
        workflow_mix = []
        for card in stage_cards:
            cnt = card['count']
            if not cnt:
                continue
            workflow_mix.append({
                'key': card['key'],
                'label': card['label'],
                'count': cnt,
                'percent': round(100.0 * cnt / wf_denom, 2),
                'color': card['color'],
            })

        payment_denom = paid_invoice_count + unpaid_invoice_count + draft_invoices
        payment_denom = payment_denom or 1
        payment_mix = []
        for pkey, plabel, pcnt, pcolor in (
            ('paid', _('Paid'), paid_invoice_count, '#22c55e'),
            ('unpaid', _('Unpaid'), unpaid_invoice_count, '#ef4444'),
            ('draft', _('Draft'), draft_invoices, '#eab308'),
        ):
            if not pcnt:
                continue
            payment_mix.append({
                'filter': pkey,
                'label': plabel,
                'count': pcnt,
                'percent': round(100.0 * pcnt / payment_denom, 2),
                'color': pcolor,
            })

        postal_pending = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pending_postal_status_stats(scope_domain)
        pod_markable = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_markable_stats(scope_domain)
        pod_status_cards = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_cards(scope_domain)
        pod_status_groups = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_groups(scope_domain)

        return {
            'currency_id': Currency.id,
            'currency_symbol': Currency.symbol or '₹',
            'decimals': Currency.decimal_places,
            'loan_domain': scope_domain,
            'pending_billing_domain': [
                ('state', '=', 'pending'),
                ('loan_id', 'in', loan_ids or [0]),
            ],
            'postal_pending_status_domain': postal_pending['domain'],
            'filters': {
                'region_id': int(region_id) if region_id else False,
                'state_id': int(state_id) if state_id else False,
                'batch_number': batch_number or False,
            },
            'kpis': {
                'total_loans': total,
                'total_batches': len(batch_keys),
                'running_jobs': running_jobs,
                'total_case_managers': total_case_managers,
                'total_arbitrators': total_arbitrators,
                'movable_cases': movable_cases,
                'postal_status_pending_count': postal_pending['count'],
                'postal_status_pending_notice_1': postal_pending['notice_1_count'],
                'postal_status_pending_interim_1': postal_pending['interim_order_1_count'],
                'postal_status_pending_amount': postal_pending['estimated_amount'],
                'pod_markable_count': pod_markable['count'],
                'pod_markable_notice_1': pod_markable['notice_1_count'],
                'pod_markable_interim_1': pod_markable['interim_order_1_count'],
                'pod_markable_award': pod_markable['award_count'],
                'simulation_available': self.env[
                    'bharat.loan.flow.simulation'
                ].dashboard_simulation_available(
                    region_id=region_id,
                    state_id=state_id,
                    batch_number=batch_number,
                ),
                'active_exposure_rows': active_followup,
                'delivered_or_lok': lok_done,
                'pos_ratio_pct': pos_ratio,
                'unique_customers': uniq_borrowers,
                'total_pos_amount': round(total_pos, 2),
                'total_claim_amount': round(total_claim, 2),
                'hearings_today': hearings_today,
                'pending_dispatch': pending_dispatch,
                'draft_invoices': draft_invoices,
                'cases_without_arbitrator': cases_no_arbitrator,
                'pending_award_upload': pending_award_upload,
                'loan_activities_due': activities_open,
                'paid_invoices': paid_invoice_count,
                'unpaid_invoices': unpaid_invoice_count,
                'total_invoices': total_invoices,
                'total_invoice_amount': total_invoice_amount,
                'paid_invoice_amount': paid_invoice_amount,
                'unpaid_invoice_amount': unpaid_invoice_amount,
                'unbilled_cases': unbilled_cases,
                'pending_billing_charges': pending_billing_charges,
                'pending_billing_amount': pending_billing_amount,
            },
            'unbilled_charges_pipeline': unbilled_charges_pipeline,
            'monthly_created': monthly_series,
            'batch_volume': batch_volume,
            'batch_volume_stages': batch_volume_stages['batches'],
            'batch_volume_stage_legend': batch_volume_stages['legend'],
            'product_mix': pie,
            'branch_mix': branch_mix,
            'location_mix': location_mix,
            'workflow_mix': workflow_mix,
            'payment_mix': payment_mix,
            'entity_cards': entity_cards,
            'stage_cards': stage_cards,
            'pod_status_cards': pod_status_cards,
            'pod_status_groups': pod_status_groups,
            'processes': self.env['bharat.process.run'].dashboard_snapshot(
                page=jobs_page, page_size=jobs_page_size,
            ),
            'case_vault': self.env['bharat.case.vault.batch'].dashboard_snapshot(
                limit=vault_limit,
            ),
        }

    # ── Role dashboards (Case Manager / Arbitrator) ───────────────────────

    PROGRESS_BUCKET_SPECS = (
        ('commencement', 'Commencement', '#64748b', 'fa-flag-o'),
        ('notice_1', 'Notice 1', '#3b82f6', 'fa-envelope-o'),
        ('notice_2', 'Notice 2', '#2563eb', 'fa-envelope-open-o'),
        ('notice_3', 'Notice 3', '#1d4ed8', 'fa-envelope'),
        ('hearing_1', 'Hearing 1', '#8b5cf6', 'fa-video-camera'),
        ('hearing_2', 'Hearing 2', '#7c3aed', 'fa-gavel'),
        ('hearing_3', 'Hearing 3', '#6d28d9', 'fa-gavel'),
        ('award', 'Award', '#ef4444', 'fa-trophy'),
    )

    @api.model
    def _dashboard_parse_dates(self, date_from=None, date_to=None):
        def _to_date(val):
            if not val:
                return None
            if isinstance(val, str):
                return fields.Date.from_string(val[:10])
            return val
        return _to_date(date_from), _to_date(date_to)

    def _case_progress_bucket_code(self):
        """Pipeline bucket for dashboards (commencement + billing milestones)."""
        self.ensure_one()
        code = self._milestone_code()
        if code:
            return code
        return self.bharat_arbitration_bill_stage()

    @api.model
    def _case_manager_dashboard_domain(self):
        user = self.env.user
        if user.bharat_role == 'case_manager':
            return [('case_manager_id', '=', user.id)]
        return []

    @api.model
    def _arbitrator_dashboard_domain(self):
        return [('arbitrator_id', '=', self.env.user.id)]

    @api.model
    def _billing_stats_for_loans(self, loans, date_from=None, date_to=None):
        """Arbitration invoice KPIs scoped to the given loan set."""
        date_from, date_to = self._dashboard_parse_dates(date_from, date_to)
        extra = []
        if date_from:
            extra.append(('invoice_date', '>=', date_from))
        if date_to:
            extra.append(('invoice_date', '<=', date_to))

        moves = self._dashboard_arbitration_moves_for_loans(
            loans, extra_domain=extra or None,
        )
        draft = moves.filtered(lambda m: m.state == 'draft')
        posted = moves.filtered(lambda m: m.state == 'posted')
        paid = posted.filtered(lambda m: m.payment_state in ('paid', 'in_payment'))
        unpaid = posted.filtered(
            lambda m: m.payment_state not in ('paid', 'in_payment')
            and (m.amount_residual or 0) > 0
        )

        all_moves = self._dashboard_arbitration_moves_for_loans(loans)
        cases_due = 0
        for loan in loans:
            if loan._case_progress_bucket_code() == 'commencement':
                continue
            loan_moves = all_moves.filtered(
                lambda m, lid=loan.id: (
                    (m.bharat_loan_id and m.bharat_loan_id.id == lid)
                    or lid in m.bharat_annexure_line_ids.mapped('loan_id').ids
                    or (
                        loan.loan_number
                        and loan.loan_number in ' '.join(m.invoice_line_ids.mapped('name') or [])
                    )
                )
            )
            if not loan_moves:
                cases_due += 1

        return {
            'cases_due_for_invoice': cases_due,
            'draft_invoices': len(draft),
            'paid_invoices': len(paid),
            'posted_unpaid_invoices': len(unpaid),
            'total_invoices': len(moves),
            'total_invoice_amount': round(sum(moves.mapped('amount_total')), 2),
            'total_due_amount': round(sum(unpaid.mapped('amount_residual')), 2),
            'total_received_amount': round(
                sum(paid.mapped(lambda m: (m.amount_total or 0) - (m.amount_residual or 0))),
                2,
            ),
            'total_invoiced_amount': round(sum(posted.mapped('amount_total')), 2),
        }

    @api.model
    def _dashboard_invoice_domains_for_loans(self, loans, date_from=None, date_to=None):
        """Account.move domains for role-dashboard invoice drill-down."""
        date_from, date_to = self._dashboard_parse_dates(date_from, date_to)
        extra = []
        if date_from:
            extra.append(('invoice_date', '>=', date_from))
        if date_to:
            extra.append(('invoice_date', '<=', date_to))
        base_moves = self._dashboard_arbitration_moves_for_loans(
            loans, extra_domain=extra or None,
        )

        def _domain(moves):
            return [('id', 'in', moves.ids or [0])]

        paid = base_moves.filtered(
            lambda m: m.state == 'posted' and m.payment_state in ('paid', 'in_payment')
        )
        unpaid = base_moves.filtered(
            lambda m: m.state == 'posted'
            and m.payment_state not in ('paid', 'in_payment')
            and (m.amount_residual or 0) > 0
        )
        draft = base_moves.filtered(lambda m: m.state == 'draft')
        return {
            'all': _domain(base_moves),
            'paid': _domain(paid),
            'unpaid': _domain(unpaid),
            'draft': _domain(draft),
        }

    @api.model
    def _dashboard_hearing_award_cards(self, bucket_cards):
        """Hearing 1–3 and final award cards for arbitrator dashboard."""
        cards = []
        for card in bucket_cards:
            if card['key'] not in ('hearing_1', 'hearing_2', 'hearing_3', 'award'):
                continue
            row = dict(card)
            if row['key'] == 'award':
                row['label'] = _('Final Award')
            cards.append(row)
        return cards

    @api.model
    def _dashboard_recent_cases(self, loans, limit=12):
        """Recently touched cases for role dashboards."""
        spec_map = {s[0]: s for s in self.PROGRESS_BUCKET_SPECS}
        ordered = loans.sorted(
            key=lambda l: l.write_date or l.create_date or fields.Datetime.now(),
            reverse=True,
        )
        rows = []
        for loan in ordered[:limit]:
            code = loan._case_progress_bucket_code()
            spec = spec_map.get(code)
            rows.append({
                'id': loan.id,
                'loan_number': loan.loan_number or loan.case_number or '',
                'customer_name': loan.customer_name or '',
                'milestone_code': code or '',
                'milestone_label': spec[1] if spec else (code or '—'),
                'milestone_color': spec[2] if spec else '#64748b',
                'hearing_datetime': (
                    fields.Datetime.to_string(loan.hearing_datetime)
                    if loan.hearing_datetime else ''
                ),
            })
        return rows

    @api.model
    def _bucket_cards_from_loans(self, loans, base_domain=None):
        total = len(loans)
        counts = defaultdict(int)
        ids_by_bucket = defaultdict(list)
        for loan in loans:
            code = loan._case_progress_bucket_code()
            counts[code] += 1
            ids_by_bucket[code].append(loan.id)

        milestones = self._milestone_master_ordered()
        milestone_by_code = {m.code: m for m in milestones}
        billing_flags = self.env['bharat.loan.milestone'].dashboard_billing_flags_by_code()
        cards = []
        for key, default_label, default_color, default_icon in self.PROGRESS_BUCKET_SPECS:
            cnt = counts.get(key, 0)
            bucket_ids = ids_by_bucket.get(key, [])
            open_domain = [('id', 'in', bucket_ids or [0])]
            milestone = milestone_by_code.get(key)
            sty = self.STAGE_STYLE.get(key, {})
            cards.append({
                'key': key,
                'id': milestone.id if milestone else False,
                'label': (milestone.name if milestone else None) or default_label,
                'count': cnt,
                'percent': round(100.0 * cnt / total, 1) if total else 0.0,
                'color': sty.get('color', default_color),
                'icon': sty.get(
                    'icon',
                    (milestone.icon if milestone else None) or default_icon,
                ),
                'open_domain': open_domain,
                'loan_ids': bucket_ids,
                **billing_flags.get(key, {
                    'creates_unbilled_charge': False,
                    'billing_badge_icon': False,
                    'billing_badge_title': False,
                    'billing_milestone_label': False,
                }),
            })
        return cards, total

    @api.model
    def _hearings_today_count(self, loan_domain):
        tzname = self.env.user.tz or 'UTC'
        tz = pytz.timezone(tzname)
        today = fields.Date.context_today(self)
        start_local = tz.localize(datetime.combine(today, dt_time.min))
        end_local = tz.localize(datetime.combine(today, dt_time.max))
        start_s = fields.Datetime.to_string(start_local.astimezone(pytz.UTC).replace(tzinfo=None))
        end_s = fields.Datetime.to_string(end_local.astimezone(pytz.UTC).replace(tzinfo=None))
        loans = self.search(loan_domain)
        if not loans:
            return 0
        return self.env['bharat.loan.hearing.line'].sudo().search_count([
            ('loan_id', 'in', loans.ids),
            ('hearing_datetime', '>=', start_s),
            ('hearing_datetime', '<=', end_s),
        ])

    @api.model
    def _upcoming_hearings(self, loan_domain, limit=8):
        now = fields.Datetime.now()
        loans = self.search(loan_domain)
        if not loans:
            return []
        lines = self.env['bharat.loan.hearing.line'].sudo().search(
            [
                ('loan_id', 'in', loans.ids),
                ('hearing_datetime', '>=', now),
            ],
            order='hearing_datetime asc',
            limit=limit,
        )
        rows = []
        for line in lines:
            loan = line.loan_id
            rows.append({
                'id': line.id,
                'loan_id': loan.id,
                'loan_number': loan.loan_number or '',
                'customer_name': loan.customer_name or '',
                'hearing_datetime': fields.Datetime.to_string(line.hearing_datetime),
                'meeting_link': (
                    (line.calendar_event_id.videocall_location if line.calendar_event_id else '')
                    or line.meeting_link
                    or ''
                ),
            })
        return rows

    @api.model
    def get_progress_bucket_domain(self, bucket_key, base_domain=None):
        """Domain for opening cases in one progress bucket."""
        domain = list(base_domain or [])
        loans = self.search(domain)
        ids = loans.filtered(
            lambda l: l._case_progress_bucket_code() == bucket_key
        ).ids
        return [('id', 'in', ids or [0])]

    @api.model
    def _dashboard_chart_palette(self):
        return (
            '#6366f1', '#06b6d4', '#8b5cf6', '#22c55e', '#eab308',
            '#ef4444', '#f97316', '#64748b', '#14b8a6', '#a855f7',
        )

    @api.model
    def _dashboard_payment_mix(self, paid_count, unpaid_count, draft_count):
        denom = paid_count + unpaid_count + draft_count
        if not denom:
            return []
        specs = (
            ('paid', _('Paid'), paid_count, '#22c55e'),
            ('unpaid', _('Unpaid'), unpaid_count, '#ef4444'),
            ('draft', _('Draft'), draft_count, '#eab308'),
        )
        return [
            {
                'filter': fkey,
                'label': label,
                'count': cnt,
                'percent': round(100.0 * cnt / denom, 2),
                'color': pcolor,
            }
            for fkey, label, cnt, pcolor in specs
            if cnt
        ]

    @api.model
    def _dashboard_breakdown_from_loans(self, loans, base_domain=None):
        """Portfolio-style chart payloads scoped to a loan recordset."""
        if base_domain is None:
            base_domain = [('id', 'in', loans.ids or [0])]
        bucket_cards, _total = self._bucket_cards_from_loans(loans, base_domain=base_domain)
        workflow_mix = [
            {
                'key': card['key'],
                'label': card['label'],
                'count': card['count'],
                'percent': card['percent'],
                'color': card['color'],
            }
            for card in bucket_cards
            if card['count']
        ]
        stage_cards = [dict(card) for card in bucket_cards]

        palette = self._dashboard_chart_palette()
        no_batch_label = _('No batch')
        by_batch = defaultdict(lambda: {'count': 0, 'batch_key': ''})
        by_branch = defaultdict(lambda: {'total': 0, 'branch_name': 'Unassigned branch'})
        by_location = defaultdict(lambda: {'total': 0, 'name': 'Unassigned location'})
        by_product_label = defaultdict(int)

        for loan in loans:
            batch_no = (loan.batch_number or '').strip()
            batch_label = batch_no or no_batch_label
            by_batch[batch_label]['count'] += 1
            by_batch[batch_label]['batch_key'] = batch_no

            if loan.branch_id:
                bkey = loan.branch_id.id
                bname = loan.branch_id.display_name
            else:
                bkey = -1
                bname = 'Unassigned branch'
            by_branch[bkey]['total'] += 1
            by_branch[bkey]['branch_name'] = bname

            if loan.location_id:
                lid = loan.location_id.id
                lname = loan.location_id.display_name
            else:
                lid = -1
                lname = (loan.location or '').strip() or 'Unassigned location'
            by_location[lid]['total'] += 1
            by_location[lid]['name'] = lname

            pcl = (
                loan.product_class_id.display_name
                if loan.product_class_id
                else (loan.product_classification or loan.product or 'Unclassified')
            )
            by_product_label[pcl] += 1

        batch_pay = self._dashboard_batch_payment_breakdown(
            loans, no_batch_label=no_batch_label,
        )
        batch_volume = self._dashboard_batch_volume_payload(batch_pay, no_batch_label)
        batch_stage = self._dashboard_batch_stage_breakdown(
            loans, no_batch_label=no_batch_label,
        )
        batch_volume_stages = self._dashboard_batch_volume_stage_payload(
            batch_stage, no_batch_label,
        )

        prod_items = sorted(by_product_label.items(), key=lambda x: -x[1])
        prod_denom = sum(by_product_label.values()) or 1
        product_mix = []
        for i, (label, cnt) in enumerate(prod_items[:10]):
            product_mix.append({
                'label': label,
                'count': cnt,
                'percent': round(100.0 * cnt / prod_denom, 2),
                'color': palette[i % len(palette)],
            })
        prod_other = sum(c for _lbl, c in prod_items[10:])
        if prod_other:
            product_mix.append({
                'label': 'Other',
                'count': prod_other,
                'percent': round(100.0 * prod_other / prod_denom, 2),
                'color': '#94a3b8',
            })

        branch_items = sorted(by_branch.items(), key=lambda kv: kv[1]['total'], reverse=True)
        branch_denom = sum(v['total'] for _k, v in branch_items) or 1
        branch_mix = []
        for i, (bid, agg) in enumerate(branch_items[:12]):
            cnt = agg['total']
            branch_mix.append({
                'id': bid,
                'label': agg.get('branch_name') or 'Unassigned branch',
                'count': cnt,
                'percent': round(100.0 * cnt / branch_denom, 2),
                'color': palette[i % len(palette)],
            })
        branch_other = sum(v['total'] for _k, v in branch_items[12:])
        if branch_other:
            branch_mix.append({
                'label': 'Other',
                'count': branch_other,
                'percent': round(100.0 * branch_other / branch_denom, 2),
                'color': '#94a3b8',
            })

        loc_items = sorted(by_location.items(), key=lambda kv: kv[1]['total'], reverse=True)
        loc_denom = sum(v['total'] for _k, v in loc_items) or 1
        location_mix = []
        for i, (lid, agg) in enumerate(loc_items[:12]):
            cnt = agg['total']
            location_mix.append({
                'id': lid,
                'label': agg['name'],
                'count': cnt,
                'percent': round(100.0 * cnt / loc_denom, 2),
                'color': palette[i % len(palette)],
            })
        loc_other = sum(v['total'] for _k, v in loc_items[12:])
        if loc_other:
            location_mix.append({
                'label': 'Other',
                'count': loc_other,
                'percent': round(100.0 * loc_other / loc_denom, 2),
                'color': '#94a3b8',
            })

        return {
            'stage_cards': stage_cards,
            'workflow_mix': workflow_mix,
            'batch_volume': batch_volume,
            'batch_volume_stages': batch_volume_stages['batches'],
            'batch_volume_stage_legend': batch_volume_stages['legend'],
            'product_mix': product_mix,
            'branch_mix': branch_mix,
            'location_mix': location_mix,
        }

    @api.model
    def get_case_manager_dashboard_statistics(
        self, date_from=None, date_to=None,
        region_id=False, state_id=False, batch_number=False,
    ):
        """OWL dashboard: portfolio layout scoped to case manager caseload."""
        self.check_access('read')
        domain = self._dashboard_apply_scope_filters(
            self._case_manager_dashboard_domain(),
            region_id=region_id,
            state_id=state_id,
            batch_number=batch_number,
        )
        loans = self.search(domain)
        bucket_cards, total_cases = self._bucket_cards_from_loans(loans)
        billing = self._billing_stats_for_loans(loans, date_from, date_to)
        breakdown = self._dashboard_breakdown_from_loans(loans, base_domain=domain)
        Currency = self.env.company.currency_id

        unbilled_charges_pipeline = self.env[
            'bharat.loan.billing.event'
        ].dashboard_pending_charges_pipeline(loans.ids)
        batch_keys = {b for b in loans.mapped('batch_number') if b}

        payment_mix = self._dashboard_payment_mix(
            billing.get('paid_invoices', 0),
            billing.get('posted_unpaid_invoices', 0),
            billing.get('draft_invoices', 0),
        )
        postal_pending = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pending_postal_status_stats(domain)
        pod_status_cards = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_cards(domain)
        pod_status_groups = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_groups(domain)

        return {
            'currency_id': Currency.id,
            'currency_symbol': Currency.symbol or '₹',
            'decimals': Currency.decimal_places,
            'date_from': date_from,
            'date_to': date_to,
            'scope_label': (
                'My assigned cases'
                if self.env.user.bharat_role == 'case_manager'
                else 'All cases'
            ),
            'kpis': {
                'total_cases': total_cases,
                'total_loans': total_cases,
                'total_batches': len(batch_keys),
                'postal_status_pending_count': postal_pending['count'],
                'postal_status_pending_notice_1': postal_pending['notice_1_count'],
                'postal_status_pending_interim_1': postal_pending['interim_order_1_count'],
                'postal_status_pending_amount': postal_pending['estimated_amount'],
                'hearings_today': self._hearings_today_count(domain),
                'unbilled_cases': unbilled_charges_pipeline['total']['cases'],
                'pending_billing_charges': unbilled_charges_pipeline['total']['count'],
                'pending_billing_amount': unbilled_charges_pipeline['total']['amount'],
                'paid_invoice_amount': billing.get('total_received_amount', 0),
                'unpaid_invoice_amount': billing.get('total_due_amount', 0),
                'paid_invoices': billing.get('paid_invoices', 0),
                'unpaid_invoices': billing.get('posted_unpaid_invoices', 0),
                **billing,
            },
            'bucket_cards': bucket_cards,
            'payment_mix': payment_mix,
            'pending_billing_domain': [
                ('state', '=', 'pending'),
                ('loan_id', 'in', loans.ids or [0]),
            ],
            'unbilled_charges_pipeline': unbilled_charges_pipeline,
            'postal_pending_status_domain': postal_pending['domain'],
            'loan_domain': domain,
            'recent_cases': self._dashboard_recent_cases(loans),
            'hearing_stage_cards': self._dashboard_hearing_award_cards(bucket_cards),
            'pod_status_cards': pod_status_cards,
            'pod_status_groups': pod_status_groups,
            'invoice_domains': self._dashboard_invoice_domains_for_loans(
                loans, date_from, date_to,
            ),
            'filters': {
                'region_id': int(region_id) if region_id else False,
                'state_id': int(state_id) if state_id else False,
                'batch_number': batch_number or False,
            },
            **breakdown,
        }

    @api.model
    def get_arbitrator_dashboard_statistics(
        self, date_from=None, date_to=None,
        region_id=False, state_id=False, batch_number=False,
    ):
        """OWL dashboard: portfolio layout scoped to arbitrator caseload."""
        self.check_access('read')
        domain = self._dashboard_apply_scope_filters(
            self._arbitrator_dashboard_domain(),
            region_id=region_id,
            state_id=state_id,
            batch_number=batch_number,
        )
        loans = self.search(domain)
        bucket_cards, total_cases = self._bucket_cards_from_loans(loans)
        billing = self._billing_stats_for_loans(loans, date_from, date_to)
        breakdown = self._dashboard_breakdown_from_loans(loans, base_domain=domain)
        upcoming = self._upcoming_hearings(domain)
        awards = sum(len(loan.award_document_ids) for loan in loans)
        hearing_cases = sum(
            c['count'] for c in bucket_cards
            if c['key'] in ('hearing_1', 'hearing_2', 'hearing_3')
        )
        Currency = self.env.company.currency_id

        payment_mix = self._dashboard_payment_mix(
            billing.get('paid_invoices', 0),
            billing.get('posted_unpaid_invoices', 0),
            billing.get('draft_invoices', 0),
        )
        pod_status_cards = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_cards(domain)
        pod_status_groups = self.env[
            'bharat.loan.postal.dispatch'
        ].dashboard_pod_status_groups(domain)

        return {
            'currency_id': Currency.id,
            'currency_symbol': Currency.symbol or '₹',
            'decimals': Currency.decimal_places,
            'date_from': date_from,
            'date_to': date_to,
            'scope_label': 'My arbitrator cases',
            'kpis': {
                'total_cases': total_cases,
                'total_loans': total_cases,
                'hearings_today': self._hearings_today_count(domain),
                'upcoming_hearings_count': len(upcoming),
                'hearing_cases': hearing_cases,
                'awards_uploaded': awards,
                'awards_pending': len(
                    loans.filtered(
                        lambda l: l._milestone_code() == 'award' and not l.award_document_ids
                    )
                ),
                'paid_invoice_amount': billing.get('total_received_amount', 0),
                'unpaid_invoice_amount': billing.get('total_due_amount', 0),
                'paid_invoices': billing.get('paid_invoices', 0),
                'unpaid_invoices': billing.get('posted_unpaid_invoices', 0),
                **billing,
            },
            'bucket_cards': bucket_cards,
            'payment_mix': payment_mix,
            'upcoming_hearings': upcoming,
            'loan_domain': domain,
            'recent_cases': self._dashboard_recent_cases(loans),
            'hearing_stage_cards': self._dashboard_hearing_award_cards(bucket_cards),
            'pod_status_cards': pod_status_cards,
            'pod_status_groups': pod_status_groups,
            'invoice_domains': self._dashboard_invoice_domains_for_loans(
                loans, date_from, date_to,
            ),
            'filters': {
                'region_id': int(region_id) if region_id else False,
                'state_id': int(state_id) if state_id else False,
                'batch_number': batch_number or False,
            },
            **breakdown,
        }
