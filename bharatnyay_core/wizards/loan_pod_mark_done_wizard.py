# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanPodMarkDoneWizard(models.TransientModel):
    _name = 'bharat.loan.pod.mark.done.wizard'
    _description = 'Mark POD delivery rows as delivered (accrue charges)'

    dispatch_count = fields.Integer(string='Delivery rows', readonly=True)
    notice_1_count = fields.Integer(string='Notice 1 pending', readonly=True)
    interim_1_count = fields.Integer(string='Hearing 1 pending', readonly=True)
    award_count = fields.Integer(string='Award pending', readonly=True)
    filter_region_id = fields.Many2one('bharat.region', string='Filter region', readonly=True)
    filter_state_id = fields.Many2one('res.country.state', string='Filter state', readonly=True)
    filter_batch_number = fields.Char(string='Filter batch', readonly=True)

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
        stats = self.env['bharat.loan.postal.dispatch'].dashboard_pod_markable_stats(domain)
        vals.update({
            'dispatch_count': stats['count'],
            'notice_1_count': stats['notice_1_count'],
            'interim_1_count': stats['interim_order_1_count'],
            'award_count': stats['award_count'],
            'filter_region_id': region_id or False,
            'filter_state_id': state_id or False,
            'filter_batch_number': batch_number or False,
        })
        return vals

    def action_confirm(self):
        self.ensure_one()
        if not self.dispatch_count:
            raise UserError(_('No pending POD delivery rows in the current filter.'))
        result = self.env['bharat.loan'].action_dashboard_mark_pod_done(
            region_id=self.filter_region_id.id if self.filter_region_id else False,
            state_id=self.filter_state_id.id if self.filter_state_id else False,
            batch_number=self.filter_batch_number or False,
        )
        if isinstance(result, dict) and result.get('type'):
            return result
        return {'type': 'ir.actions.act_window_close'}
