# -*- coding: utf-8 -*-

def migrate(cr, version):
    from odoo.addons.bharatnyay_core.hooks import migrate_user_role_assignments_to_res_users

    migrate_user_role_assignments_to_res_users(cr)
