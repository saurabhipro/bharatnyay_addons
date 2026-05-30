# -*- coding: utf-8 -*-


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Mapping = env['base_import.mapping'].sudo()
    for mapping in Mapping.search([('res_model', '=', 'bharat.loan'), ('field_name', '=', 'state_id')]):
        if (mapping.column_name or '').strip().lower() == 'state':
            mapping.field_name = 'borrower_state'

    Mapping.flush_model()
