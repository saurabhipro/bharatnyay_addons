# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.arbitration_billing import BILLABLE_MILESTONE_CODES
from ..models.loan_milestone import POSTAL_BILLING_MILESTONE_CODES


class BharatLoanBillingTestWizard(models.TransientModel):
    _name = 'bharat.loan.billing.test.wizard'
    _description = 'Manually queue unbilled charges (testing)'

    batch_id = fields.Many2one(
        'bharat.loan.batch',
        string='Batch',
        help='Accrue for every case in this batch (optional if cases are selected below).',
    )
    loan_ids = fields.Many2many(
        'bharat.loan',
        'bharat_billing_test_loan_rel',
        'wizard_id',
        'loan_id',
        string='Cases',
        help='Leave empty when using a batch, or pick specific cases.',
    )
    milestone_id = fields.Many2one(
        'bharat.loan.milestone',
        string='Billing stage',
        required=True,
        domain=[('code', 'in', list(BILLABLE_MILESTONE_CODES))],
    )
    preview_count = fields.Integer(compute='_compute_preview', string='Cases to process')
    preview_hint = fields.Char(compute='_compute_preview')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        self.env['bharat.loan.batch']._sync_from_loans()
        if self.env.context.get('active_model') == 'bharat.loan' and self.env.context.get('active_id'):
            res['loan_ids'] = [(6, 0, [self.env.context['active_id']])]
        return res

    def _target_loans(self):
        self.ensure_one()
        if self.loan_ids:
            return self.loan_ids
        if self.batch_id:
            return self.env['bharat.loan'].search([('batch_number', '=', self.batch_id.name)])
        return self.env['bharat.loan']

    @api.depends('batch_id', 'loan_ids', 'milestone_id')
    def _compute_preview(self):
        for wiz in self:
            loans = wiz._target_loans()
            wiz.preview_count = len(loans)
            if not wiz.milestone_id:
                wiz.preview_hint = _('Select a billing stage.')
            elif not loans:
                wiz.preview_hint = _('Pick a batch or at least one case.')
            else:
                wiz.preview_hint = _(
                    '%(n)s case(s) — stage “%(stage)s”. Rows that already exist are skipped.'
                ) % {'n': len(loans), 'stage': wiz.milestone_id.name}

    def action_apply(self):
        self.ensure_one()
        if not self.milestone_id:
            raise UserError(_('Select a billing stage.'))
        if self.milestone_id.code in POSTAL_BILLING_MILESTONE_CODES:
            raise UserError(
                _('Notice 1, Hearing 1, and Award charges accrue only when POD post office '
                  'status is set to a billable status — use Excel POD import or '
                  'Update POD on the case.')
            )
        loans = self._target_loans()
        if not loans:
            raise UserError(_('Pick a batch or at least one case.'))

        Event = self.env['bharat.loan.billing.event']
        created = 0
        skipped = 0
        code = self.milestone_id.code
        for loan in loans:
            had = Event.search_count([
                ('loan_id', '=', loan.id),
                ('milestone_code', '=', code),
                ('state', '!=', 'cancelled'),
            ])
            event = Event.bharat_accrue_for_loan(
                loan,
                self.milestone_id,
                accrual_trigger='milestone_exit',
            )
            if not event:
                skipped += 1
            elif had:
                skipped += 1
            else:
                created += 1

        message = _(
            'Created %(created)s pending charge(s). Skipped %(skipped)s (already exists or not billable).'
        ) % {'created': created, 'skipped': skipped}
        if not created and skipped:
            raise UserError(message)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Unbilled charges'),
            'res_model': 'bharat.loan.billing.event',
            'view_mode': 'list,form',
            'domain': [
                ('loan_id', 'in', loans.ids),
                ('milestone_code', '=', code),
            ],
            'context': {'search_default_pending': 1},
            'target': 'current',
        }
