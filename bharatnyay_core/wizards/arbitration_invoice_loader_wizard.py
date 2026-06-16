<<<<<<< Updated upstream
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.arbitration_billing import BILLABLE_MILESTONE_CODES
from ..models.loan_milestone import POSTAL_BILLING_MILESTONE_CODES


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
    scope_summary = fields.Char(string='Scope', compute='_compute_preview')
    scope_detail = fields.Char(string='Scope detail', compute='_compute_preview')
    billing_stage_label = fields.Char(string='Billing stage', compute='_compute_preview')
    preview_lender_count = fields.Integer(string='Lenders', compute='_compute_preview')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        self.env['bharat.loan.batch']._sync_from_loans()
        wiz = self.new(res)
        events = wiz._scoped_pending_events(apply_saved_filters=False)
        res.update(wiz._auto_selection_vals(events))
        return res

    @api.model
    def _dashboard_context(self):
        ctx = self.env.context
        return {
            'region_id': ctx.get('dashboard_region_id') or False,
            'state_id': ctx.get('dashboard_state_id') or False,
            'batch_number': ctx.get('dashboard_batch_number') or False,
            'milestone_code': ctx.get('bharat_billing_milestone_code') or False,
        }

    def _dashboard_loan_ids(self):
        dash = self._dashboard_context()
        Loan = self.env['bharat.loan'].sudo()
        if not Loan._dashboard_scope_filters_active(
            dash['region_id'], dash['state_id'], dash['batch_number'],
        ):
            return None
        domain = Loan._dashboard_apply_scope_filters(
            [],
            region_id=dash['region_id'],
            state_id=dash['state_id'],
            batch_number=dash['batch_number'],
        )
        return Loan.search(domain).ids

    def _milestone_codes_from_context(self):
        dash = self._dashboard_context()
        code = dash.get('milestone_code')
        if code and code != 'total':
            return [code]
        if code == 'total':
            return list(POSTAL_BILLING_MILESTONE_CODES)
        return None

    def _scoped_pending_events(self, apply_saved_filters=True):
        """Pending charges for preview/apply, honouring dashboard scope and wizard filters."""
        self.ensure_one()
        Event = self.env['bharat.loan.billing.event']
        milestone_codes = None
        if apply_saved_filters and self.milestone_ids:
            milestone_codes = self.milestone_ids.mapped('code') or None
        elif not apply_saved_filters:
            milestone_codes = self._milestone_codes_from_context()

        batch_names = None
        if apply_saved_filters and self.batch_ids:
            batch_names = self.batch_ids.mapped('name') or None

        events = Event.bharat_search_pending(
            company_ids=None,
            batch_names=batch_names,
            milestone_codes=milestone_codes,
        )
        loan_ids = self._dashboard_loan_ids()
        if loan_ids is not None:
            events = events.filtered(lambda e, lids=set(loan_ids): e.loan_id.id in lids)
        return events

    def _auto_selection_vals(self, events):
        """Auto-fill batch and billing stage selections (hidden from the simplified UI)."""
        Batch = self.env['bharat.loan.batch'].sudo()
        Milestone = self.env['bharat.loan.milestone'].sudo()
        vals = {
            'company_ids': [(5, 0, 0)],
            'move_id': False,
        }

        dash = self._dashboard_context()
        batch_number = (dash.get('batch_number') or '').strip()
        if batch_number and batch_number != '__none__':
            batch = Batch.search([('name', '=', batch_number)], limit=1)
            vals['batch_ids'] = [(6, 0, batch.ids)] if batch else [(5, 0, 0)]
        else:
            batch_names = sorted({
                (name or '').strip()
                for name in events.mapped('batch_number')
                if (name or '').strip()
            })
            batches = Batch.search([('name', 'in', batch_names)]) if batch_names else Batch.browse()
            vals['batch_ids'] = [(6, 0, batches.ids)]

        milestone_code = dash.get('milestone_code')
        if milestone_code and milestone_code != 'total':
            milestone = Milestone.search([('code', '=', milestone_code)], limit=1)
            vals['milestone_ids'] = [(6, 0, milestone.ids)] if milestone else [(5, 0, 0)]
        elif milestone_code == 'total':
            milestones = Milestone.search([
                ('code', 'in', list(POSTAL_BILLING_MILESTONE_CODES)),
            ])
            vals['milestone_ids'] = [(6, 0, milestones.ids)]
        else:
            codes = sorted(set(events.mapped('milestone_code')) - {False, ''})
            milestones = Milestone.search([('code', 'in', codes)]) if codes else Milestone.browse()
            vals['milestone_ids'] = [(6, 0, milestones.ids)]

        return vals

    def _pending_events(self):
        self.ensure_one()
        return self._scoped_pending_events(apply_saved_filters=True)

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
                wiz.scope_summary = ''
                wiz.scope_detail = ''
                wiz.billing_stage_label = ''
                wiz.preview_lender_count = 0
            else:
                batch_labels = sorted({
                    (name or '').strip() or _('No batch')
                    for name in events.mapped('batch_number')
                })
                stage_labels = sorted(set(events.mapped('milestone_label')) - {False, ''})
                lenders = len(events.mapped('company_id'))
                hint = _(
                    '%(n)s charge(s) ready to invoice across %(lenders)s lender(s).'
                ) % {
                    'n': len(events),
                    'lenders': lenders,
                }
                batches_text = ', '.join(batch_labels[:4]) + (
                    _(' (+%(n)s more)') % {'n': len(batch_labels) - 4}
                    if len(batch_labels) > 4 else ''
                )
                stages_text = ', '.join(stage_labels) or _('All')
                wiz.preview_hint = hint
                wiz.scope_summary = _(
                    'Batches: %(batches)s · Stages: %(stages)s'
                ) % {
                    'batches': batches_text,
                    'stages': stages_text,
                }
                wiz.scope_detail = _(
                    'Batches: %(batches)s · Stages: %(stages)s · %(hint)s'
                ) % {
                    'batches': batches_text,
                    'stages': stages_text,
                    'hint': hint,
                }
                wiz.preview_lender_count = lenders
                if wiz.milestone_ids:
                    if len(wiz.milestone_ids) == 1:
                        wiz.billing_stage_label = wiz.milestone_ids[0].name
                    else:
                        wiz.billing_stage_label = _('%s stages') % len(wiz.milestone_ids)
                else:
                    wiz.billing_stage_label = stages_text

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
=======
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.arbitration_billing import BILLABLE_MILESTONE_CODES
from ..models.loan_milestone import POSTAL_BILLING_MILESTONE_CODES


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
    scope_summary = fields.Char(string='Scope', compute='_compute_preview')
    scope_detail = fields.Char(string='Scope detail', compute='_compute_preview')
    billing_stage_label = fields.Char(string='Billing stage', compute='_compute_preview')
    preview_lender_count = fields.Integer(string='Lenders', compute='_compute_preview')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        self.env['bharat.loan.batch']._sync_from_loans()
        wiz = self.new(res)
        events = wiz._scoped_pending_events(apply_saved_filters=False)
        res.update(wiz._auto_selection_vals(events))
        return res

    @api.model
    def _dashboard_context(self):
        ctx = self.env.context
        return {
            'region_id': ctx.get('dashboard_region_id') or False,
            'state_id': ctx.get('dashboard_state_id') or False,
            'batch_number': ctx.get('dashboard_batch_number') or False,
            'milestone_code': ctx.get('bharat_billing_milestone_code') or False,
        }

    def _dashboard_loan_ids(self):
        dash = self._dashboard_context()
        Loan = self.env['bharat.loan'].sudo()
        if not Loan._dashboard_scope_filters_active(
            dash['region_id'], dash['state_id'], dash['batch_number'],
        ):
            return None
        domain = Loan._dashboard_apply_scope_filters(
            [],
            region_id=dash['region_id'],
            state_id=dash['state_id'],
            batch_number=dash['batch_number'],
        )
        return Loan.search(domain).ids

    def _milestone_codes_from_context(self):
        dash = self._dashboard_context()
        code = dash.get('milestone_code')
        if code and code != 'total':
            return [code]
        if code == 'total':
            return list(POSTAL_BILLING_MILESTONE_CODES)
        return None

    def _scoped_pending_events(self, apply_saved_filters=True):
        """Pending charges for preview/apply, honouring dashboard scope and wizard filters."""
        self.ensure_one()
        Event = self.env['bharat.loan.billing.event']
        milestone_codes = None
        if apply_saved_filters and self.milestone_ids:
            milestone_codes = self.milestone_ids.mapped('code') or None
        elif not apply_saved_filters:
            milestone_codes = self._milestone_codes_from_context()

        batch_names = None
        if apply_saved_filters and self.batch_ids:
            batch_names = self.batch_ids.mapped('name') or None

        events = Event.bharat_search_pending(
            company_ids=None,
            batch_names=batch_names,
            milestone_codes=milestone_codes,
        )
        loan_ids = self._dashboard_loan_ids()
        if loan_ids is not None:
            events = events.filtered(lambda e, lids=set(loan_ids): e.loan_id.id in lids)
        return events

    def _auto_selection_vals(self, events):
        """Auto-fill batch and billing stage selections (hidden from the simplified UI)."""
        Batch = self.env['bharat.loan.batch'].sudo()
        Milestone = self.env['bharat.loan.milestone'].sudo()
        vals = {
            'company_ids': [(5, 0, 0)],
            'move_id': False,
        }

        dash = self._dashboard_context()
        batch_number = (dash.get('batch_number') or '').strip()
        if batch_number and batch_number != '__none__':
            batch = Batch.search([('name', '=', batch_number)], limit=1)
            vals['batch_ids'] = [(6, 0, batch.ids)] if batch else [(5, 0, 0)]
        else:
            batch_names = sorted({
                (name or '').strip()
                for name in events.mapped('batch_number')
                if (name or '').strip()
            })
            batches = Batch.search([('name', 'in', batch_names)]) if batch_names else Batch.browse()
            vals['batch_ids'] = [(6, 0, batches.ids)]

        milestone_code = dash.get('milestone_code')
        if milestone_code and milestone_code != 'total':
            milestone = Milestone.search([('code', '=', milestone_code)], limit=1)
            vals['milestone_ids'] = [(6, 0, milestone.ids)] if milestone else [(5, 0, 0)]
        elif milestone_code == 'total':
            milestones = Milestone.search([
                ('code', 'in', list(POSTAL_BILLING_MILESTONE_CODES)),
            ])
            vals['milestone_ids'] = [(6, 0, milestones.ids)]
        else:
            codes = sorted(set(events.mapped('milestone_code')) - {False, ''})
            milestones = Milestone.search([('code', 'in', codes)]) if codes else Milestone.browse()
            vals['milestone_ids'] = [(6, 0, milestones.ids)]

        return vals

    def _pending_events(self):
        self.ensure_one()
        return self._scoped_pending_events(apply_saved_filters=True)

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
                wiz.scope_summary = ''
                wiz.scope_detail = ''
                wiz.billing_stage_label = ''
                wiz.preview_lender_count = 0
            else:
                batch_labels = sorted({
                    (name or '').strip() or _('No batch')
                    for name in events.mapped('batch_number')
                })
                stage_labels = sorted(set(events.mapped('milestone_label')) - {False, ''})
                lenders = len(events.mapped('company_id'))
                hint = _(
                    '%(n)s charge(s) ready to invoice across %(lenders)s lender(s).'
                ) % {
                    'n': len(events),
                    'lenders': lenders,
                }
                batches_text = ', '.join(batch_labels[:4]) + (
                    _(' (+%(n)s more)') % {'n': len(batch_labels) - 4}
                    if len(batch_labels) > 4 else ''
                )
                stages_text = ', '.join(stage_labels) or _('All')
                wiz.preview_hint = hint
                wiz.scope_summary = _(
                    'Batches: %(batches)s · Stages: %(stages)s'
                ) % {
                    'batches': batches_text,
                    'stages': stages_text,
                }
                wiz.scope_detail = _(
                    'Batches: %(batches)s · Stages: %(stages)s · %(hint)s'
                ) % {
                    'batches': batches_text,
                    'stages': stages_text,
                    'hint': hint,
                }
                wiz.preview_lender_count = lenders
                if wiz.milestone_ids:
                    if len(wiz.milestone_ids) == 1:
                        wiz.billing_stage_label = wiz.milestone_ids[0].name
                    else:
                        wiz.billing_stage_label = _('%s stages') % len(wiz.milestone_ids)
                else:
                    wiz.billing_stage_label = stages_text

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
            moves |= Move.bharat_create_consolidated_from_events(
                company_events,
                batch_names=batch_names,
                milestone_codes=milestone_codes,
                move=None,
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
>>>>>>> Stashed changes
