# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BharatLoanLocation(models.Model):
    _name = 'bharat.loan_location'
    _description = 'Location (office / city)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=False, tracking=True)
    region_id = fields.Many2one(
        'bharat.region',
        string='Region',
        index=True,
        tracking=True,
    )
    state_id = fields.Many2one(
        'res.country.state',
        string='State',
        index=True,
        tracking=True,
    )
    branch_id = fields.Many2one(
        'bharat.branch',
        string='Branch',
        index=True,
        tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ('bharat_loan_location_name_uniq', 'unique(name)', 'This location already exists.'),
    ]

    @api.constrains('region_id', 'state_id', 'branch_id')
    def _check_location_geography(self):
        for rec in self:
            if rec.state_id and rec.region_id and rec.state_id.region_id != rec.region_id:
                raise ValidationError(
                    'State "%(state)s" does not belong to region "%(region)s".'
                    % {
                        'state': rec.state_id.display_name,
                        'region': rec.region_id.name,
                    }
                )
            if rec.branch_id:
                if rec.region_id and rec.branch_id.region_id != rec.region_id:
                    raise ValidationError(
                        'Branch "%(branch)s" does not belong to region "%(region)s".'
                        % {'branch': rec.branch_id.name, 'region': rec.region_id.name}
                    )
                if rec.state_id and rec.branch_id.borrower_state_id != rec.state_id:
                    raise ValidationError(
                        'Branch "%(branch)s" does not belong to state "%(state)s".'
                        % {'branch': rec.branch_id.name, 'state': rec.state_id.display_name}
                    )

    @api.onchange('region_id')
    def _onchange_region_id(self):
        for rec in self:
            if rec.state_id and (
                not rec.region_id or rec.state_id.region_id != rec.region_id
            ):
                rec.state_id = False
            if rec.branch_id and (
                not rec.region_id or rec.branch_id.region_id != rec.region_id
            ):
                rec.branch_id = False

    @api.onchange('state_id')
    def _onchange_state_id(self):
        for rec in self:
            state = rec.state_id
            if state and state.region_id:
                rec.region_id = state.region_id
            if rec.branch_id and (
                not state or rec.branch_id.borrower_state_id != state
            ):
                rec.branch_id = False

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        for rec in self:
            branch = rec.branch_id
            if not branch:
                return
            if branch.region_id:
                rec.region_id = branch.region_id
            if branch.borrower_state_id:
                rec.state_id = branch.borrower_state_id
