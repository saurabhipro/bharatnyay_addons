# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

BHARAT_ARBITRATION_STAGE_SELECTION = [
    ('notice_1', 'Notice 1'),
    ('notice_2', 'Notice 2'),
    ('notice_3', 'Notice 3'),
    ('interim_order_1', 'Interim Order 1'),
    ('hearing_1', 'Hearing 1'),
    ('hearing_2', 'Hearing 2'),
    ('hearing_3', 'Hearing 3'),
    ('award', 'Award'),
]


class BharatArbitrationInvoiceLineLoaderWizard(models.TransientModel):
    _name = 'bharat.arbitration.invoice.line.loader.wizard'
    _description = 'Create one consolidated arbitration invoice for a batch + milestone'

    move_id = fields.Many2one(
        'account.move',
        string='Draft invoice (optional)',
        ondelete='cascade',
        domain=[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')],
        help='Leave empty to create a new posted invoice, or pick a draft invoice to fill.',
    )
    batch_number = fields.Char(
        string='Loan batch number',
        required=True,
        help='All pending charges for this batch and milestone are consolidated into one invoice.',
    )
    milestone_code = fields.Selection(
        selection=BHARAT_ARBITRATION_STAGE_SELECTION,
        string='Milestone to bill',
        required=True,
        help='Bill pending charges accrued when cases exited this milestone.',
    )
    preview_case_count = fields.Integer(
        string='Pending charges',
        compute='_compute_preview',
    )
    preview_total_amount = fields.Monetary(
        string='Estimated total',
        compute='_compute_preview',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    preview_hint = fields.Char(compute='_compute_preview')

    @api.depends('batch_number', 'milestone_code')
    def _compute_preview(self):
        Event = self.env['bharat.loan.billing.event']
        labels = dict(BHARAT_ARBITRATION_STAGE_SELECTION)
        for wiz in self:
            bn = (wiz.batch_number or '').strip()
            code = wiz.milestone_code
            if not bn or not code:
                wiz.preview_case_count = 0
                wiz.preview_total_amount = 0.0
                wiz.preview_hint = ''
                continue
            events = Event.bharat_pending_for_batch_milestone(bn, code)
            wiz.preview_case_count = len(events)
            wiz.preview_total_amount = sum(events.mapped('unit_price'))
            if events:
                wiz.currency_id = events[0].currency_id
            task = labels.get(code, code)
            if not events:
                wiz.preview_hint = _('No pending charges for batch “%s” / %s.') % (bn, task)
            else:
                wiz.preview_hint = _('%(n)s case(s) ready — one invoice line + annexure for %(task)s.') % {
                    'n': len(events),
                    'task': task,
                }

    def _bharat_backfill_pending_events(self, batch_number, milestone_code):
        """Create pending charges for cases that already passed the milestone (pre-upgrade rows)."""
        Milestone = self.env['bharat.loan.milestone']
        Event = self.env['bharat.loan.billing.event']
        target = Milestone.search([('code', '=', milestone_code)], limit=1)
        if not target:
            return Event.browse()
        loans = self.env['bharat.loan'].search([
            ('batch_number', '=', batch_number),
            ('milestone_id.sequence', '>', target.sequence),
        ])
        for loan in loans:
            Event.bharat_accrue_for_loan(loan, target)
        return Event.bharat_pending_for_batch_milestone(batch_number, milestone_code)

    def action_apply(self):
        self.ensure_one()
        batch = (self.batch_number or '').strip()
        if not batch:
            raise UserError(_('Enter the loan batch number.'))
        if not self.milestone_code:
            raise UserError(_('Select the milestone to bill.'))

        Event = self.env['bharat.loan.billing.event']
        events = Event.bharat_pending_for_batch_milestone(batch, self.milestone_code)
        if not events:
            events = self._bharat_backfill_pending_events(batch, self.milestone_code)
        if not events:
            labels = dict(BHARAT_ARBITRATION_STAGE_SELECTION)
            raise UserError(
                _('No billable cases for batch “%s” and milestone “%s”. '
                  'Advance cases past that milestone first (charges accrue on exit).')
                % (batch, labels.get(self.milestone_code, self.milestone_code))
            )

        move = self.env['account.move'].bharat_create_consolidated_from_events(
            events,
            batch,
            self.milestone_code,
            move=self.move_id,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': move.display_name,
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
