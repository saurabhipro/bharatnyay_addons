# -*- coding: utf-8 -*-
from odoo import api, models


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @api.model
    def _get_demo_data_bank(self, company=False):
        """Skip duplicate demo bank rows when an archived account already exists.

        Odoo demo uses acc_number BANK{company_id}34567890. The core check only
        looks at active bank_ids, so a previously archived demo bank triggers
        create() and raises UserError on chart demo install.
        """
        company = company or self.env.company
        partner = company.root_id.partner_id
        acc_number = f'BANK{company.id}34567890'
        Bank = self.env['res.partner.bank'].sudo().with_context(active_test=False)
        existing = Bank.search([
            ('partner_id', '=', partner.id),
            ('acc_number', '=', acc_number),
        ], limit=1)
        if existing:
            if not existing.active:
                existing.write({'active': True})
            return {}
        return super()._get_demo_data_bank(company)
