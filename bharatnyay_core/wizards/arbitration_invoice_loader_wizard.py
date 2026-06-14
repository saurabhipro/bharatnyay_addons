# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatArbitrationInvoiceLineLoaderWizard(models.TransientModel):
    _name = 'bharat.arbitration.invoice.line.loader.wizard'
    _description = 'Create consolidated arbitration invoice from pending unbilled charges'

    move_id = fields.Many2one(
        'account.move',
        string='Draft invoice (optional)',
        ondelete='cascade',
        domain=[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')],
        help='Leave empty to create a new posted invoice. Only used when pending charges belong to one lender.',
    )
    batch_ids = fields.Many2many(
        'bharat.loan.batch',
        'bharat_inv_loader_batch_rel',
        'wizard_id',
        'batch_id',
        string='Batches',
        help='Leave empty to include all batches with pending charges.',
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
        if fields_list is not None and 'batch_ids' not in fields_list:
            return res
        if res.get('batch_ids'):
            return res
        batch_number = (self.env.context.get('dashboard_batch_number') or '').strip()
        if not batch_number:
            batch_number = (
                self.env['bharat.loan'].bharat_get_dashboard_batch_filter() or ''
            ).strip()
        if not batch_number or batch_number == '__none__':
            return res
        Batch = self.env['bharat.loan.batch'].sudo()
        Batch._sync_from_loans()
        batch = Batch.search([('name', '=', batch_number)], limit=1)
        if batch:
            res['batch_ids'] = [(6, 0, batch.ids)]
        return res

    def _pending_events(self):
        self.ensure_one()
        Event = self.env['bharat.loan.billing.event']
        return Event.bharat_search_pending(
            batch_names=self.batch_ids.mapped('name') or None,
        )

    @api.depends('batch_ids')
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
                batches = len(set(events.mapped('batch_number')))
                wiz.preview_hint = _(
                    '%(n)s charge(s) — %(batches)s batch(es).'
                ) % {
                    'n': len(events),
                    'batches': batches,
                }

    def action_apply(self):
        self.ensure_one()
        events = self._pending_events()
        if not events:
            raise UserError(_('No pending unbilled charges match your selection.'))

        Move = self.env['account.move']
        batch_names = self.batch_ids.mapped('name') or None
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
