# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatPostOfficeStatus(models.Model):
    _name = 'bharat.post.office.status'
    _description = 'Post office / POD delivery status'
    _order = 'sequence, name'

    name = fields.Char(string='Status', required=True)
    code = fields.Char(string='Code', required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_delivered = fields.Boolean(
        string='Delivery confirmed',
        help='POD received / item delivered to addressee.',
    )
    triggers_billing = fields.Boolean(
        string='Accrue unbilled charge',
        help='When set on a postal dispatch row, queues a pending billing event '
        'for that document (parallel to case workflow progression).',
    )
    locks_case = fields.Boolean(
        string='Lock case',
        help='When set, the case form becomes read-only (e.g. RRN locked after delivery).',
    )
    description = fields.Text(string='Notes')
    setup_id = fields.Many2one(
        'bharat.case.workflow.setup',
        string='Workflow setup',
        ondelete='set null',
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        self.env['bharat.case.workflow.setup'].assign_setup_id_vals(vals_list)
        return super().create(vals_list)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Post office status code must be unique.'),
        ('name_uniq', 'unique(name)', 'Post office status name must be unique.'),
    ]
