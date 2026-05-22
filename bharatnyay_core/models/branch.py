# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BharatBranch(models.Model):
    _name = 'bharat.branch'
    _description = 'Branch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Branch', required=True, translate=False, tracking=True)
    code = fields.Char(string='Code', tracking=True)
    region_id = fields.Many2one(
        'bharat.region',
        string='Region',
        index=True,
        tracking=True,
    )
    borrower_state_id = fields.Many2one(
        'res.country.state',
        string='State',
        index=True,
        tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ('bharat_branch_name_uniq', 'unique(name)', 'This branch already exists.'),
    ]

    @api.constrains('region_id', 'borrower_state_id')
    def _check_state_matches_region(self):
        for rec in self:
            if (
                rec.region_id
                and rec.borrower_state_id
                and rec.borrower_state_id.region_id != rec.region_id
            ):
                raise ValidationError(
                    'State "%(state)s" does not belong to region "%(region)s".'
                    % {
                        'state': rec.borrower_state_id.display_name,
                        'region': rec.region_id.name,
                    }
                )

    @api.onchange('region_id')
    def _onchange_region_id(self):
        for rec in self:
            if rec.borrower_state_id and (
                not rec.region_id
                or rec.borrower_state_id.region_id != rec.region_id
            ):
                rec.borrower_state_id = False

    @api.onchange('borrower_state_id')
    def _onchange_borrower_state_id(self):
        for rec in self:
            state = rec.borrower_state_id
            if not state or not state.region_id:
                continue
            if not rec.region_id:
                rec.region_id = state.region_id
            elif state.region_id != rec.region_id:
                rec.borrower_state_id = False
