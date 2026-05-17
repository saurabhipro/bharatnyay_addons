# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    bharat_arbitration_invoice = fields.Boolean(
        string='Arbitration billing invoice',
        index=True,
        help='Set when lines are added from BharatNyay loan cases (used on the dashboard KPI).',
    )

    def action_open_arbitration_line_loader(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft invoices can load arbitration lines.'))
        if self.move_type != 'out_invoice':
            raise UserError(_('Use customer invoices (out invoice).'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add arbitration lines from cases'),
            'res_model': 'bharat.arbitration.invoice.line.loader.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }
