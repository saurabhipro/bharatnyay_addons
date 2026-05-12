# -*- coding: utf-8 -*-
from odoo import fields, models


class BharatNotificationTemplate(models.Model):
    _name = 'bharat.notification.template'
    _description = 'BharatNyay Notification Template'
    _order = 'notice_type, name'

    name = fields.Char(required=True)
    notice_type = fields.Selection(
        [
            ('notice', 'Notice'),
            ('appointment_of_arbitrator', 'Appointment of Arbitrator'),
            ('arbitrator_appointed', 'Arbitrator Appointed'),
            ('hearing', 'Hearing'),
            ('final_award', 'Final Award'),
            ('paid', 'Paid'),
        ],
        required=True,
        default='notice',
        index=True,
    )
    subject_template = fields.Char(required=True)
    body_template = fields.Text(required=True)
    active = fields.Boolean(default=True)

    def render_for_loan(self, loan):
        """Render subject/body with safe named placeholders."""
        self.ensure_one()
        vals = {
            'loan_number': loan.loan_number or '',
            'customer_name': loan.customer_name or '',
            'respondent_name': loan.respondent_name or '',
            'branch': loan.branch_id.name or loan.branch or '',
            'state': loan.borrower_state_id.name or loan.borrower_state or '',
            'region': loan.region_id.name or loan.region or '',
            'product': loan.product or loan.product_class_id.name or loan.product_classification or '',
            'current_pos': f"{loan.current_pos or 0:.2f}",
            'claim_amount': f"{loan.claim_amount or 0:.2f}",
            'workflow_phase': loan.workflow_phase or '',
        }
        subject = (self.subject_template or '').format_map(vals)
        body = (self.body_template or '').format_map(vals)
        return subject, body
