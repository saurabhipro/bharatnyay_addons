# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.postal_dispatch import POSTAL_DOCUMENT_TYPES


class BharatLoanPostalStatusWizard(models.TransientModel):
    _name = 'bharat.loan.postal.status.wizard'
    _description = 'Update postal POD and delivery status'

    loan_id = fields.Many2one(
        'bharat.loan',
        string='Case',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    document_type = fields.Selection(
        POSTAL_DOCUMENT_TYPES,
        string='Document',
        required=True,
        readonly=True,
    )
    dispatch_id = fields.Many2one(
        'bharat.loan.postal.dispatch',
        string='Postal dispatch',
        readonly=True,
        ondelete='cascade',
    )
    loan_display = fields.Char(string='Case', compute='_compute_labels', readonly=True)
    document_label = fields.Char(string='Document', compute='_compute_labels', readonly=True)

    pod = fields.Char(string='POD / tracking no.')
    post_office_status_id = fields.Many2one(
        'bharat.post.office.status',
        string='Post office status',
        domain=[('active', '=', True)],
        ondelete='restrict',
    )
    dispatch_date = fields.Date(string='Dispatch date')
    delivery_date = fields.Date(string='Delivery date')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        dispatch = self.env['bharat.loan.postal.dispatch'].browse(
            self.env.context.get('default_dispatch_id')
        )
        if not dispatch.exists():
            return vals
        if 'pod' in fields_list and not vals.get('pod') and dispatch.pod:
            vals['pod'] = dispatch.pod
        if (
            'post_office_status_id' in fields_list
            and not vals.get('post_office_status_id')
            and dispatch.post_office_status_id
        ):
            vals['post_office_status_id'] = dispatch.post_office_status_id.id
        if 'dispatch_date' in fields_list and not vals.get('dispatch_date') and dispatch.dispatch_date:
            vals['dispatch_date'] = dispatch.dispatch_date
        if 'delivery_date' in fields_list and not vals.get('delivery_date') and dispatch.delivery_date:
            vals['delivery_date'] = dispatch.delivery_date
        return vals

    @api.depends('loan_id', 'document_type')
    def _compute_labels(self):
        labels = dict(POSTAL_DOCUMENT_TYPES)
        for wiz in self:
            loan = wiz.loan_id
            wiz.loan_display = loan.display_name if loan else ''
            wiz.document_label = labels.get(wiz.document_type, wiz.document_type or '')

    def action_save(self):
        self.ensure_one()
        loan = self.loan_id
        if not (self.pod or '').strip() and not self.post_office_status_id:
            raise UserError(_('Enter a POD / tracking number or select a post office status.'))

        Dispatch = self.env['bharat.loan.postal.dispatch']
        dispatch = self.dispatch_id or Dispatch.ensure_for_loan(loan, self.document_type)
        if not dispatch:
            raise UserError(_('Could not open postal tracking for this document.'))

        vals = {}
        pod = (self.pod or '').strip()
        if pod:
            vals['pod'] = pod
        if self.dispatch_date:
            vals['dispatch_date'] = self.dispatch_date
        if self.delivery_date:
            vals['delivery_date'] = self.delivery_date
        if self.post_office_status_id:
            vals['post_office_status_id'] = self.post_office_status_id.id
            if self.post_office_status_id.is_delivered and not self.delivery_date:
                vals['delivery_date'] = self.dispatch_date or fields.Date.context_today(self)
        if vals:
            dispatch.write(vals)

        status_name = self.post_office_status_id.name if self.post_office_status_id else _('(unchanged)')
        loan.message_post(
            body=_(
                'Postal tracking updated for %(doc)s.\n'
                'POD: %(pod)s\n'
                'Status: %(status)s'
            ) % {
                'doc': self.document_label or self.document_type,
                'pod': pod or dispatch.pod or '—',
                'status': status_name,
            },
        )
        return {'type': 'ir.actions.act_window_close'}
