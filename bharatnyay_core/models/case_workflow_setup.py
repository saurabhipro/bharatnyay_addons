# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BharatCaseWorkflowSetup(models.Model):
    _name = 'bharat.case.workflow.setup'
    _description = 'Case workflow configuration hub'
    _rec_name = 'name'

    name = fields.Char(default='Case workflow', required=True)

    milestone_ids = fields.One2many(
        'bharat.loan.milestone',
        'setup_id',
        string='Workflow milestones',
    )
    post_office_status_ids = fields.One2many(
        'bharat.post.office.status',
        'setup_id',
        string='Post office statuses',
    )

    @api.model
    def _ensure_singleton(self):
        setup = self.search([], limit=1)
        if not setup:
            setup = self.create({'name': 'Case workflow'})
        self._link_orphan_masters(setup)
        return setup

    @api.model
    def link_existing_masters(self):
        """Link legacy milestone / POD rows to the singleton (module upgrade hook)."""
        self._ensure_singleton()
        return True

    @api.model
    def _link_orphan_masters(self, setup):
        if not setup:
            return
        Milestone = self.env['bharat.loan.milestone']
        Status = self.env['bharat.post.office.status']
        Milestone.search([('setup_id', '=', False)]).write({'setup_id': setup.id})
        Status.search([('setup_id', '=', False)]).write({'setup_id': setup.id})

    @api.model
    def assign_setup_id_vals(self, vals_list):
        """Set setup_id on new master rows once the hub table exists."""
        setup = self._ensure_singleton()
        for vals in vals_list:
            vals.setdefault('setup_id', setup.id)
        return vals_list
