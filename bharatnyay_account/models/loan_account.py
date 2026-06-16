# -*- coding: utf-8 -*-
from odoo import _, api, models


class BharatLoanAccount(models.Model):
    _inherit = 'bharat.loan'

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
