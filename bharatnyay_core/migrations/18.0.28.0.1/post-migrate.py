# -*- coding: utf-8 -*-

def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.users'].search([('bharat_role', '!=', False)])._sync_bharat_role_groups()
