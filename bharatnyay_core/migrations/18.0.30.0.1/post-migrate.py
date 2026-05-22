# -*- coding: utf-8 -*-

def migrate(cr, version):
    from odoo.addons.bharatnyay_core.hooks import migrate_borrower_state_to_country_state

    migrate_borrower_state_to_country_state(cr)
