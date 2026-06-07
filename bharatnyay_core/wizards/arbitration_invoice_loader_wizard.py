# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.arbitration_billing import BILLABLE_MILESTONE_CODES


class BharatArbitrationInvoiceLineLoaderWizard(models.TransientModel):
    _name = 'bharat.arbitration.invoice.line.loader.wizard'
    _description = 'Create consolidated arbitration invoice from pending unbilled charges'

    move_id = fields.Many2one(
        'account.move',
        string='Draft invoice (optional)',
        ondelete='cascade',
        domain=[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')],
        help='Leave empty to create a new posted invoice. Only used when a single lender is selected.',
    )
    company_ids = fields.Many2many(
        'res.company',
        'bharat_inv_loader_company_rel',
        'wizard_id',
        'company_id',
        string='Lenders',
        help='Leave empty to include all lenders with pending charges.',
    )
    batch_ids = fields.Many2many(
        'bharat.loan.batch',
        'bharat_inv_loader_batch_rel',
        'wizard_id',
        'batch_id',
        string='Batches',
        help='Leave empty to include all batches with pending charges.',
    )
    milestone_ids = fields.Many2many(
        'bharat.loan.milestone',
        'bharat_inv_loader_milestone_rel',
        'wizard_id',
        'milestone_id',
        string='Billing stages',
        domain=[('code', 'in', list(BILLABLE_MILESTONE_CODES))],
        help='Leave empty to include all pending billing stages.',
    )
    preview_case_count = fields.Integer(string='Pending charges', compute='_compute_preview')
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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        self.env['bharat.loan.batch']._sync_from_loans()
        return res

    def _pending_events(self):
        self.ensure_one()
        Event = self.env['bharat.loan.billing.event']
        return Event.bharat_search_pending(
            company_ids=self.company_ids.ids or None,
            batch_names=self.batch_ids.mapped('name') or None,
            milestone_codes=self.milestone_ids.mapped('code') or None,
        )

    @api.depends('company_ids', 'batch_ids', 'milestone_ids')
    def _compute_preview(self):
        for wiz in self:
            events = wiz._pending_events()
            wiz.preview_case_count = len(events)
            wiz.preview_total_amount = sum(events.mapped('unit_price'))
            if events:
                wiz.currency_id = events[0].currency_id
            if not events:
                wiz.preview_hint = _('No pending unbilled charges match this selection.')
            else:
                lenders = len(events.mapped('company_id'))
                batches = len(set(events.mapped('batch_number')))
                stages = len(set(events.mapped('milestone_code')))
                wiz.preview_hint = _(
                    '%(n)s charge(s) — %(lenders)s lender(s), %(batches)s batch(es), %(stages)s stage(s).'
                ) % {
                    'n': len(events),
                    'lenders': lenders,
                    'batches': batches,
                    'stages': stages,
                }

    def action_apply(self):
        self.ensure_one()
        events = self._pending_events()
        if not events:
            raise UserError(_('No pending unbilled charges match your selection.'))

        Move = self.env['account.move']
        batch_names = self.batch_ids.mapped('name') or None
        milestone_codes = self.milestone_ids.mapped('code') or None
        companies = events.mapped('company_id')
        moves = Move.browse()

        for company in companies:
            company_events = events.filtered(lambda e: e.company_id == company)
            draft_move = self.move_id if len(companies) == 1 else None
            if draft_move and draft_move.company_id != company:
                draft_move = None
            moves |= Move.bharat_create_consolidated_from_events(
                company_events,
                batch_names=batch_names,
                milestone_codes=milestone_codes,
                move=draft_move,
            )

        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': moves.display_name,
                'res_model': 'account.move',
                'res_id': moves.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consolidated invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
            'target': 'current',
        }
