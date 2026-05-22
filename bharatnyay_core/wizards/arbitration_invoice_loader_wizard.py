# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatArbitrationInvoiceLineLoaderWizard(models.TransientModel):
    _name = 'bharat.arbitration.invoice.line.loader.wizard'
    _description = 'Bill a loan batch on a customer invoice (aggregated milestone lines)'

    move_id = fields.Many2one(
        'account.move',
        string='Draft invoice',
        required=True,
        ondelete='cascade',
        domain=[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')],
    )
    batch_number = fields.Char(
        string='Loan batch number',
        required=True,
        help='Matches Loan sheet ▸ Batch number. All cases in this batch are billed together; '
        'invoice lines aggregate by milestone task (Notice 1–3, Hearing 1–3, Award) using your billing products.',
    )
    preview_case_count = fields.Integer(string='Cases found', compute='_compute_preview')

    @api.depends('batch_number')
    def _compute_preview(self):
        Loan = self.env['bharat.loan']
        for wiz in self:
            bn = (wiz.batch_number or '').strip()
            if not bn:
                wiz.preview_case_count = 0
                continue
            wiz.preview_case_count = Loan.search_count([('batch_number', '=', bn)])

    def action_apply(self):
        self.ensure_one()
        move = self.move_id
        if move.state != 'draft' or move.move_type != 'out_invoice':
            raise UserError(_('Open this wizard from a draft customer invoice.'))

        batch = (self.batch_number or '').strip()
        if not batch:
            raise UserError(_('Enter the loan batch number.'))

        loans = self.env['bharat.loan'].search([('batch_number', '=', batch)])
        if not loans:
            raise UserError(_('No loans found with batch number “%s”.') % batch)

        cmds = self.env['account.move'].bharat_prepare_arbitration_invoice_line_commands(loans, batch)
        if not cmds:
            raise UserError(_('No billable milestone lines were produced (check case workflow stages).'))

        move.with_context(check_move_validity=False).write({
            'invoice_line_ids': cmds,
            'bharat_arbitration_invoice': True,
            'bharat_invoice_batch_ref': batch,
            'ref': move.ref or (_('BharatNyay batch %s') % batch),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': move.display_name,
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
