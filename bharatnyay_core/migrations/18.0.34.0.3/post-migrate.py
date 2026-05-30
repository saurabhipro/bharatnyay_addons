# -*- coding: utf-8 -*-


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Loan = env['bharat.loan'].sudo()
    Company = env['res.company'].sudo()

    for company in Company.search([]):
        if not company.loan_stage_line_ids:
            company._assign_default_loan_stages()

    missing_stage = Loan.search([('state_id', '=', False)])
    for company in missing_stage.mapped('company_id'):
        stage = Loan._get_default_workflow_stage(company)
        if not stage:
            continue
        company_loans = missing_stage.filtered(lambda r: r.company_id == company)
        company_loans.write({
            'state_id': stage.id,
            'workflow_section': stage.section or 1,
            'workflow_phase': stage.phase or '',
        })

    auto = Loan.search([
        ('case_manager_manual', '=', False),
        '|', ('branch_id', '!=', False), ('location_id', '!=', False),
    ])
    if auto:
        env.add_to_compute(Loan._fields['case_manager_id'], auto)

    env.flush_all()
