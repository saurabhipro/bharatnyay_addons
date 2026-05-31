# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BharatLoanLocation(models.Model):
    _name = 'bharat.loan_location'
    _description = 'Location (office / city)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Location', required=True, translate=False, tracking=True)
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
    active = fields.Boolean(default=True, tracking=True)

    

    @api.constrains('region_id', 'state_id')
    def _check_state_matches_region(self):
        if self.env.context.get('from_import') or self.env.context.get('import_file'):
            return
        for rec in self:
            if (
                rec.region_id
                and rec.state_id
                and rec.state_id.region_id != rec.region_id
            ):
                raise ValidationError(
                    'State "%(state)s" does not belong to region "%(region)s".'
                    % {
                        'state': rec.state_id.display_name,
                        'region': rec.region_id.name,
                    }
                )

    @api.onchange('region_id')
    def _onchange_region_id(self):
        for rec in self:
            if rec.state_id and (
                not rec.region_id or rec.state_id.region_id != rec.region_id
            ):
                rec.state_id = False

    @api.onchange('state_id')
    def _onchange_state_id(self):
        for rec in self:
            state = rec.state_id
            if not state or not state.region_id:
                continue
            if not rec.region_id:
                rec.region_id = state.region_id
            elif state.region_id != rec.region_id:
                rec.state_id = False
