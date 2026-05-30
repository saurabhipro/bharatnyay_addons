# -*- coding: utf-8 -*-
from odoo import api, fields, models

DEFAULT_LOAN_STAGES = (
    {
        'code': 'commencement',
        'name': 'Commencement',
        'sequence': 1,
        'section': 1,
        'phase': 'Commencement',
    },
    {
        'code': 'notice',
        'name': 'Notice',
        'sequence': 2,
        'section': 21,
        'phase': 'Notice',
    },
    {
        'code': 'arbitrator_appointed',
        'name': 'Arbitrator Appointed',
        'sequence': 3,
        'section': 11,
        'phase': 'Arbitrator Appointed',
    },
    {
        'code': 'hearing',
        'name': 'Hearing',
        'sequence': 4,
        'section': 24,
        'phase': 'Hearing',
    },
    {
        'code': 'final_award',
        'name': 'Award',
        'sequence': 5,
        'section': 31,
        'phase': 'Award',
    },
)


class BharatLoanStage(models.Model):
    _name = 'bharat.loan.stage'
    _description = 'Loan workflow stage (master)'
    _order = 'sequence, id'

    name = fields.Char(string='Stage', required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Technical code',
        required=True,
        index=True,
        help='Stable key used by automation (e.g. hearing, notice). Do not change after go-live.',
    )
    section = fields.Integer(
        string='Workflow section',
        default=1,
        help='Arbitration / dispute section number (1–31).',
    )
    phase = fields.Char(string='Phase label')
    active = fields.Boolean(default=True)
    fold = fields.Boolean(string='Folded in Kanban')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Stage code must be unique.'),
    ]

    @api.model
    def _ensure_default_master_stages(self):
        if self.search_count([]):
            return
        self.create([dict(spec) for spec in DEFAULT_LOAN_STAGES])


class BharatCompanyLoanStage(models.Model):
    _name = 'bharat.company.loan.stage'
    _description = 'Company loan stage assignment'
    _order = 'sequence, id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='cascade',
        index=True,
    )
    stage_id = fields.Many2one(
        'bharat.loan.stage',
        string='Stage',
        required=True,
        ondelete='restrict',
        index=True,
    )
    sequence = fields.Integer(default=10)
    is_arbitrator = fields.Boolean(
        string='Assign arbitrator',
        default=False,
        help='When enabled, cases at this stage show an Assign Arbitrator button on the loan form.',
    )
    stage_code = fields.Char(related='stage_id.code', readonly=True)
    stage_name = fields.Char(related='stage_id.name', readonly=True)

    _sql_constraints = [
        (
            'company_stage_uniq',
            'unique(company_id, stage_id)',
            'Each stage can only be assigned once per company.',
        ),
    ]
