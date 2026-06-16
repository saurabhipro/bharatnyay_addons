# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanMilestoneAdvanceWizard(models.TransientModel):
    _name = 'bharat.loan.milestone.advance.wizard'
    _description = 'Bulk advance cases by one milestone'

    case_count = fields.Integer(string='Cases to advance', readonly=True)
    filter_region_id = fields.Many2one('bharat.region', string='Filter region', readonly=True)
    filter_state_id = fields.Many2one('res.country.state', string='Filter state', readonly=True)
    filter_batch_number = fields.Char(string='Filter batch', readonly=True)
    generate_pdfs = fields.Boolean(
        string='Generate PDFs during advance',
        default=False,
        help='Render notice/hearing PDFs immediately. Leave off for faster testing.',
    )
    send_email = fields.Boolean(
        string='Send email to borrower',
        default=False,
    )
    send_sms = fields.Boolean(
        string='Send SMS to borrower',
        default=False,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = self.env.context
        region_id = ctx.get('dashboard_region_id') or False
        state_id = ctx.get('dashboard_state_id') or False
        batch_number = ctx.get('dashboard_batch_number') or False
        domain = self.env['bharat.loan']._dashboard_apply_scope_filters(
            [], region_id=region_id, state_id=state_id, batch_number=batch_number,
        )
        eligible = self.env['bharat.loan'].search(domain).filtered(
            lambda l: not l.is_case_locked and l._next_milestone_record()
        )
        vals.update({
            'case_count': len(eligible),
            'filter_region_id': region_id or False,
            'filter_state_id': state_id or False,
            'filter_batch_number': batch_number or False,
        })
        return vals

    def action_confirm(self):
        self.ensure_one()
        if not self.case_count:
            raise UserError(_('No cases in the current filter can be advanced.'))
        result = self.env['bharat.loan'].action_dashboard_move_to_next_stage(
            region_id=self.filter_region_id.id if self.filter_region_id else False,
            state_id=self.filter_state_id.id if self.filter_state_id else False,
            batch_number=self.filter_batch_number or False,
            generate_pdfs=self.generate_pdfs,
            send_email=self.send_email,
            send_sms=self.send_sms,
        )
        if isinstance(result, dict) and result.get('type'):
            return result
        return {'type': 'ir.actions.act_window_close'}
