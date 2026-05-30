# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.tools.misc import format_datetime


class BharatNotificationTemplate(models.Model):
    _name = 'bharat.notification.template'
    _description = 'BharatNyay Notification Template'
    _order = 'notice_type, name'

    name = fields.Char(required=True)
    notice_type = fields.Selection(
        [
            ('notice', 'Notice'),
            ('arbitrator_appointed', 'Arbitrator Appointed'),
            ('hearing', 'Hearing'),
            ('final_award', 'Award'),
        ],
        required=True,
        default='notice',
        index=True,
    )
    subject_template = fields.Char(required=True)
    body_template = fields.Text(required=True)
    active = fields.Boolean(default=True)

    def render_for_loan(self, loan):
        """Render subject/body with named placeholders (unknown tags become empty)."""
        self.ensure_one()
        tz = self.env.user.tz or self.env.context.get('tz') or 'UTC'
        hearing_dt = ''
        if loan.hearing_datetime:
            hearing_dt = format_datetime(self.env, loan.hearing_datetime, tz=tz, dt_format='medium')
        arb_name = ''
        if loan.arbitrator_id:
            arb_name = loan.arbitrator_id.name or ''
        elif loan.arbitrator_name:
            arb_name = loan.arbitrator_name

        vals = {
            'loan_number': loan.loan_number or '',
            'case_number': loan.case_number or '',
            'customer_name': loan.customer_name or '',
            'respondent_name': loan.respondent_name or '',
            'branch': loan.branch_id.name or loan.branch or '',
            'state': loan.borrower_state_id.name or loan.borrower_state or '',
            'region': loan.region_id.name or loan.region or '',
            'product': loan.product or loan.product_class_id.name or loan.product_classification or '',
            'current_pos': f'{loan.current_pos or 0:.2f}',
            'claim_amount': f'{loan.claim_amount or 0:.2f}',
            'workflow_phase': loan.workflow_phase or '',
            'arbitrator_name': arb_name,
            'hearing_datetime': hearing_dt,
            'nbfc_name': loan.company_id.name if loan.company_id else '',
            'outstanding_amount': f'{loan.current_pos or 0:.2f}',
        }

        class _Safe(dict):
            def __missing__(self, key):
                return ''

        smap = _Safe(vals)
        subject = (self.subject_template or '').format_map(smap)
        body = (self.body_template or '').format_map(smap)
        return subject, body
