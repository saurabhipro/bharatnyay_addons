# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResCompany(models.Model):
    _inherit = 'res.company'

    loan_stage_line_ids = fields.One2many(
        'bharat.company.loan.stage',
        'company_id',
        string='Loan stages',
    )
    loan_ids = fields.One2many(
        'bharat.loan',
        'company_id',
        string='Cases',
    )
    loan_count = fields.Integer(
        string='# Cases',
        compute='_compute_loan_stats',
    )
    loan_stage_count = fields.Integer(
        string='# Workflow stages',
        compute='_compute_loan_stats',
    )

    @api.depends('loan_ids', 'loan_stage_line_ids')
    def _compute_loan_stats(self):
        for company in self:
            company.loan_count = len(company.loan_ids)
            company.loan_stage_count = len(company.loan_stage_line_ids)

    def action_open_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cases'),
            'res_model': 'bharat.loan',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.id)],
            'context': {'default_company_id': self.id},
        }

    def _loan_stages_ordered(self):
        self.ensure_one()
        return self.loan_stage_line_ids.sorted('sequence').mapped('stage_id')

    def _get_loan_stage_by_code(self, code):
        self.ensure_one()
        line = self.loan_stage_line_ids.filtered(
            lambda row: row.stage_id.code == code
        )[:1]
        return line.stage_id if line else self.env['bharat.loan.stage']

    def _assign_default_loan_stages(self):
        Stage = self.env['bharat.loan.stage']
        Line = self.env['bharat.company.loan.stage']
        Stage._ensure_default_master_stages()
        master_stages = Stage.search([], order='sequence, id')
        for company in self:
            if company.loan_stage_line_ids:
                continue
            Line.create([
                {
                    'company_id': company.id,
                    'stage_id': stage.id,
                    'sequence': stage.sequence,
                }
                for stage in master_stages
            ])

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._assign_default_loan_stages()
        return companies
