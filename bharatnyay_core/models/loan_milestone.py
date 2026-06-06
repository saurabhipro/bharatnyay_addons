# -*- coding: utf-8 -*-
from odoo import api, fields, models

DEFAULT_LOAN_MILESTONES = (
    {
        'code': 'commencement',
        'name': 'Commencement',
        'sequence': 1,
        'section': 1,
        'phase': 'Commencement',
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
        'auto_invoice_on_exit': False,
        'auto_assign_case_manager': True,
        'auto_assign_arbitrator': False,
    },
    {
        'code': 'notice_2',
        'name': 'Notice 2',
        'sequence': 3,
        'section': 21,
        'phase': 'Notice 2',
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'notice_3',
        'name': 'Notice 3',
        'sequence': 4,
        'section': 21,
        'phase': 'Notice 3',
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'hearing_1',
        'name': 'Hearing 1',
        'sequence': 5,
        'section': 24,
        'phase': 'Hearing 1',
        'auto_invoice_on_exit': False,
        'auto_assign_arbitrator': True,
        'is_arbitrator': True,
    },
    {
        'code': 'hearing_2',
        'name': 'Hearing 2',
        'sequence': 6,
        'section': 24,
        'phase': 'Hearing 2',
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'hearing_3',
        'name': 'Hearing 3',
        'sequence': 7,
        'section': 24,
        'phase': 'Hearing 3',
        'auto_invoice_on_exit': False,
    },
    {
        'code': 'award',
        'name': 'Award',
        'sequence': 8,
        'section': 31,
        'phase': 'Award',
        'auto_invoice_on_exit': False,
        'locks_case': True,
    },
)


class BharatLoanMilestone(models.Model):
    _name = 'bharat.loan.milestone'
    _description = 'Loan workflow milestone'
    _order = 'sequence, id'

    name = fields.Char(string='Milestone', required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Technical code',
        required=True,
        index=True,
        help='Stable key used by automation (commencement, notice_1, hearing_1, award, …).',
    )
    section = fields.Integer(
        string='Workflow section',
        default=1,
        help='Arbitration / dispute section number (1–31).',
    )
    phase = fields.Char(string='Phase label')
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
