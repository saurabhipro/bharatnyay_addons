# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanAssignArbitratorWizard(models.TransientModel):
    _name = 'bharat.loan.assign.arbitrator.wizard'
    _description = 'Assign arbitrator to loan case'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    user_id = fields.Many2one(
        'res.users',
        string='Arbitrator',
        required=True,
        domain=[('bharat_role', '=', 'arbitrator')],
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(
            self.env.context.get('default_loan_id') or self.env.context.get('active_id')
        )
        if loan:
            vals.setdefault('loan_id', loan.id)
            if loan.arbitrator_id and loan.arbitrator_id.bharat_role == 'arbitrator':
                vals.setdefault('user_id', loan.arbitrator_id.id)
        return vals

    def action_submit(self):
        self.ensure_one()
        if not self.loan_id:
            raise UserError(_('Loan is required.'))
        if not self.user_id:
            raise UserError(_('Please select an arbitrator.'))
        if self.user_id.bharat_role != 'arbitrator':
            raise UserError(_('Please select a user with the Arbitrator role.'))
        self.loan_id.write({'arbitrator_id': self.user_id.id})
        self.loan_id.message_post(
            body=_('Arbitrator assigned: <b>%s</b>') % (self.user_id.name,),
        )
        return {'type': 'ir.actions.act_window_close'}
