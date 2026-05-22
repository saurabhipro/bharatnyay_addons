# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


STAGE_LINE_ORDER = ('notice_1', 'notice_2', 'notice_3', 'hearing_1', 'hearing_2', 'hearing_3', 'award')


class AccountMove(models.Model):
    _inherit = 'account.move'

    bharat_arbitration_invoice = fields.Boolean(
        string='Arbitration billing invoice',
        index=True,
        help='Set when lines are built from BharatNyay loan batches / milestones.',
    )
    bharat_invoice_batch_ref = fields.Char(
        string='Loan batch ref.',
        index=True,
        help='Import/batch number shared by the cases billed on this invoice.',
    )

    def action_open_arbitration_line_loader(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft invoices can load arbitration lines.'))
        if self.move_type != 'out_invoice':
            raise UserError(_('Use customer invoices (out invoice).'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bill loan batch (milestones)'),
            'res_model': 'bharat.arbitration.invoice.line.loader.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    @api.model
    def bharat_prepare_arbitration_invoice_line_commands(self, loans, batch_display=''):
        """Build (0, 0, vals) commands: one aggregated line per milestone present in the loan set."""
        Loan = self.env['bharat.loan']
        Template = self.env['product.template'].sudo()
        labels = dict(Template._fields['bharat_arbitration_stage'].selection)

        stage_ids = {}
        for loan in loans:
            st = loan.bharat_arbitration_bill_stage()
            stage_ids.setdefault(st, []).append(loan.id)

        line_cmds = []
        for stage_key in STAGE_LINE_ORDER:
            ids = stage_ids.pop(stage_key, None)
            if not ids:
                continue
            subset = Loan.browse(ids)
            tmpl = Template.search([('bharat_arbitration_stage', '=', stage_key)], limit=2)
            if len(tmpl) != 1:
                raise UserError(
                    _('Configure exactly one billing product for milestone “%s” (found %s).')
                    % (labels.get(stage_key, stage_key), len(tmpl))
                )
            product = tmpl.product_variant_ids[:1]
            if not product:
                raise UserError(_('Product “%s” has no variant.') % tmpl.display_name)
            product = product[0]
            qty = len(subset)
            nums = subset.mapped('loan_number')
            shown = ', '.join(n for n in nums[:30] if n)
            if len(nums) > 30:
                shown += ', …'
            batch_prefix = (_('Batch %s · ') % batch_display) if batch_display else ''
            task_label = labels.get(stage_key, stage_key)
            line_name = _('%s%s — %s case(s) — %s') % (batch_prefix, task_label, qty, shown)
            line_cmds.append(
                (
                    0,
                    0,
                    {
                        'product_id': product.id,
                        'quantity': qty,
                        'name': line_name,
                    },
                )
            )
        if stage_ids:
            leftover = ', '.join(stage_ids.keys())
            raise UserError(_('Unhandled milestone keys (add products): %s') % leftover)
        return line_cmds

    @api.model
    def _bharat_demo_seed_batch_invoice(self):
        """One draft USD invoice for demo batch BN-DEMO-BILL (idempotent)."""
        if self.search([('ref', '=', 'BharatNyay BN-DEMO-BILL demo invoice')], limit=1):
            return
        loans = self.env['bharat.loan'].sudo().search([('batch_number', '=', 'BN-DEMO-BILL')])
        if len(loans) < 5:
            return
        partner = self.env.ref('bharatnyay_core.sample_partner_nbfc_billing', raise_if_not_found=False)
        if not partner:
            return
        journal = self.env['account.journal'].sudo().search(
            [('type', '=', 'sale'), ('company_id', '=', self.env.company.id)],
            limit=1,
        )
        if not journal:
            return
        try:
            cmds = self.bharat_prepare_arbitration_invoice_line_commands(loans, 'BN-DEMO-BILL')
        except UserError:
            return
        if not cmds:
            return
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        self.sudo().create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'journal_id': journal.id,
            'currency_id': usd.id if usd else self.env.company.currency_id.id,
            'invoice_line_ids': cmds,
            'bharat_arbitration_invoice': True,
            'bharat_invoice_batch_ref': 'BN-DEMO-BILL',
            'ref': 'BharatNyay BN-DEMO-BILL demo invoice',
            'narration': _(
                'Demo: one invoice covering multiple cases in batch BN-DEMO-BILL. '
                'Lines aggregate by milestone task (Notice / Hearing / Award products). '
                'Currency USD.'
            ),
        })
