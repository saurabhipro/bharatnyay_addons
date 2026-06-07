# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models

DEFAULT_MILESTONE_ICONS = {
    'commencement': 'fa-flag-checkered',
    'notice_1': 'fa-envelope-o',
    'notice_2': 'fa-envelope-open-o',
    'notice_3': 'fa-envelope',
    'hearing_1': 'fa-video-camera',
    'hearing_2': 'fa-gavel',
    'hearing_3': 'fa-gavel',
    'award': 'fa-trophy',
}

DEFAULT_LOAN_MILESTONES = (
    {
        'code': 'commencement',
        'name': 'Commencement',
        'sequence': 1,
        'section': 1,
        'phase': 'Commencement',
        'icon': 'fa-flag-checkered',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
        'auto_assign_case_manager': False,
        'auto_assign_arbitrator': False,
    },
    {
        'code': 'notice_1',
        'name': 'Notice 1',
        'sequence': 2,
        'section': 21,
        'phase': 'Notice 1',
        'icon': 'fa-envelope-o',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
        'auto_assign_case_manager': True,
        'auto_assign_arbitrator': False,
        'bill_on_milestone_exit': False,
    },
    {
        'code': 'notice_2',
        'name': 'Notice 2',
        'sequence': 3,
        'section': 21,
        'phase': 'Notice 2',
        'icon': 'fa-envelope-open-o',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'notice_3',
        'name': 'Notice 3',
        'sequence': 4,
        'section': 21,
        'phase': 'Notice 3',
        'icon': 'fa-envelope',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'hearing_1',
        'name': 'Hearing 1',
        'sequence': 5,
        'section': 24,
        'phase': 'Hearing 1',
        'icon': 'fa-video-camera',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
        'auto_assign_arbitrator': True,
        'is_arbitrator': True,
        'bill_on_milestone_exit': False,
    },
    {
        'code': 'hearing_2',
        'name': 'Hearing 2',
        'sequence': 6,
        'section': 24,
        'phase': 'Hearing 2',
        'icon': 'fa-gavel',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'hearing_3',
        'name': 'Hearing 3',
        'sequence': 7,
        'section': 24,
        'phase': 'Hearing 3',
        'icon': 'fa-gavel',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'award',
        'name': 'Award',
        'sequence': 8,
        'section': 31,
        'phase': 'Award',
        'icon': 'fa-trophy',
        'stay_days': 0,
        'auto_invoice_on_exit': False,
        'locks_case': True,
        'bill_on_milestone_exit': False,
    },
)


# Workflow entry points that accrue unbilled charges on postal delivery (POD).
POSTAL_BILLING_MILESTONE_CODES = frozenset({'notice_1', 'hearing_1', 'award'})

BILLING_BADGE_ICONS = {
    'notice_1': 'fa-file-text-o',
    'hearing_1': 'fa-legal',
    'award': 'fa-money',
}


class BharatLoanMilestone(models.Model):
    _name = 'bharat.loan.milestone'
    _description = 'Loan workflow milestone'
    _order = 'sequence, id'

    name = fields.Char(string='Stage name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Stage ID',
        required=True,
        index=True,
        help='Stable key used by automation (commencement, notice_1, hearing_1, award, …).',
    )
    icon = fields.Char(
        string='Icon',
        default='fa-circle-o',
        help='Font Awesome icon class shown on dashboards (e.g. fa-envelope-o).',
    )
    icon_html = fields.Html(
        string='Icon',
        compute='_compute_icon_html',
        sanitize=False,
    )
    stay_days = fields.Integer(
        string='Stay period (days)',
        default=0,
        help='Days a case remains in this stage before the scheduler auto-advances to the next. '
        'Leave 0 to disable auto-advance for this stage.',
    )
    section = fields.Integer(
        string='Workflow section',
        default=1,
        help='Arbitration / dispute section number (1–31).',
    )
    phase = fields.Char(string='Phase label')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    price = fields.Monetary(string='Price', currency_field='currency_id')
    fold = fields.Boolean(string='Folded in Kanban')
    is_arbitrator = fields.Boolean(
        string='Arbitrator step',
        default=False,
        help='Cases at this milestone may assign an arbitrator (legacy UI hint).',
    )
    locks_case = fields.Boolean(
        string='Locks case',
        default=False,
        help='When reached, the case form becomes read-only (e.g. final award).',
    )
    auto_invoice_on_exit = fields.Boolean(
        string='Create invoice on exit (legacy)',
        default=False,
        help='Deprecated. Leave off — billing uses pending charges + consolidated batch invoice wizard.',
    )
    bill_on_milestone_exit = fields.Boolean(
        string='Bill on milestone exit',
        default=True,
        help='When enabled, exiting this milestone queues a pending charge. '
        'When disabled, billing for this task accrues from postal delivery (Notice 1, Interim Order 1, Award).',
    )
    auto_assign_case_manager = fields.Boolean(
        string='Auto-assign case manager',
        default=False,
    )
    auto_assign_arbitrator = fields.Boolean(
        string='Auto-assign arbitrator',
        default=False,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Milestone code must be unique.'),
    ]

    @api.depends('icon', 'name', 'code')
    def _compute_icon_html(self):
        for rec in self:
            raw = (
                rec.icon
                or DEFAULT_MILESTONE_ICONS.get(rec.code or '', '')
                or 'fa-circle-o'
            ).strip()
            raw = raw.replace('fa ', '').replace('fa-', '')
            ic_class = 'fa fa-%s' % raw
            rec.icon_html = Markup(
                '<span class="bn-milestone-icon" title="%s">'
                '<i class="%s" aria-hidden="true"></i></span>'
            ) % (rec.name or '', ic_class)

    @api.model
    def _ensure_default_master_milestones(self):
        """Create or update default milestones by code (idempotent)."""
        for spec in DEFAULT_LOAN_MILESTONES:
            existing = self.search([('code', '=', spec['code'])], limit=1)
            if existing:
                existing.write({k: v for k, v in spec.items() if k != 'code'})
            else:
                self.create(dict(spec))

    @api.model
    def _default_commencement(self):
        self._ensure_default_master_milestones()
        return self.search([('code', '=', 'commencement')], limit=1)

    def creates_unbilled_charge(self):
        """True when this milestone can queue a pending billing charge (per master)."""
        self.ensure_one()
        if self.code in POSTAL_BILLING_MILESTONE_CODES:
            return True
        return bool(self.bill_on_milestone_exit)

    def billing_accrual_mode(self):
        """How unbilled charges are created for this milestone."""
        self.ensure_one()
        if self.code in POSTAL_BILLING_MILESTONE_CODES:
            return 'postal_delivery'
        if self.bill_on_milestone_exit:
            return 'milestone_exit'
        return False

    def dashboard_billing_card_fields(self):
        """JSON fields for dashboard stage / pipeline cards."""
        self.ensure_one()
        if not self.creates_unbilled_charge():
            return {
                'creates_unbilled_charge': False,
                'billing_badge_icon': False,
                'billing_badge_title': False,
            }
        mode = self.billing_accrual_mode()
        if mode == 'postal_delivery':
            title = {
                'notice_1': _('Unbilled charge on Notice 1 postal delivery'),
                'hearing_1': _('Unbilled charge on Interim Order 1 postal delivery'),
                'award': _('Unbilled charge on Award postal delivery'),
            }.get(self.code, _('Unbilled charge on postal delivery'))
            icon = BILLING_BADGE_ICONS.get(self.code, 'fa-file-text-o')
        else:
            title = _('Unbilled charge when leaving this milestone')
            icon = 'fa-sign-out'
        return {
            'creates_unbilled_charge': True,
            'billing_badge_icon': icon,
            'billing_badge_title': title,
        }

    @api.model
    def dashboard_billing_flags_by_code(self):
        self._ensure_default_master_milestones()
        return {
            m.code: m.dashboard_billing_card_fields()
            for m in self.search([])
        }
