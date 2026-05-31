# -*- coding: utf-8 -*-

def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    from odoo.addons.bharatnyay_core.hooks import (
        migrate_loan_workflow_award_final_stage,
        migrate_loan_workflow_award_final_stage_sql,
    )

    migrate_loan_workflow_award_final_stage_sql(cr)
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_loan_workflow_award_final_stage(env)
