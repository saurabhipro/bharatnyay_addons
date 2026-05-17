# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatArbitrationInvoiceLineLoaderWizard(models.TransientModel):
    _name = 'bharat.arbitration.invoice.line.loader.wizard'
    _description = 'Add customer invoice lines from loan cases (arbitration products)'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        domain=[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')],
    )
    loan_ids = fields.Many2many(
        'bharat.loan',
        string='Cases',
        required=True,
        help='One invoice line per case using the product mapped to the inferred arbitration stage.',
    )

    @api.model
    def _infer_bill_stage(self, loan):
        ws = loan.workflow_stage or ''
        n_notice = len(loan.notice_line_ids)
        n_hear = len(loan.hearing_line_ids)
        if loan.award_document_ids or ws == 'final_award':
            return 'award'
        if ws == 'hearing':
            idx = min(max(n_hear, 1), 3)
            return 'hearing_%s' % idx
        if ws in ('arbitrator_appointed', 'appointment_of_arbitrator'):
            return 'notice_3'
        idx = min(max(n_notice, 1), 3)
        return 'notice_%s' % idx

    def action_apply(self):
        self.ensure_one()
        move = self.move_id
        if move.state != 'draft' or move.move_type != 'out_invoice':
            raise UserError(_('Open this wizard from a draft customer invoice.'))

        Template = self.env['product.template'].sudo()
        labels = dict(Template._fields['bharat_arbitration_stage'].selection)
        line_cmds = []

        for loan in self.loan_ids:
            stage_key = self._infer_bill_stage(loan)
            tmpl = Template.search([('bharat_arbitration_stage', '=', stage_key)], limit=2)
            if len(tmpl) != 1:
                raise UserError(
                    _('Configure exactly one product with arbitration stage “%s” (found %s).')
                    % (labels.get(stage_key, stage_key), len(tmpl))
                )
            product = tmpl.product_variant_ids[:1]
            if not product:
                raise UserError(_('Product “%s” has no variant.') % tmpl.display_name)
            product = product[0]
            line_name = '%s — %s / %s' % (
                tmpl.name,
                loan.loan_number or loan.id,
                loan.case_number or _('no case #'),
            )
            line_cmds.append(
                (
                    0,
                    0,
                    {
                        'product_id': product.id,
                        'quantity': 1,
                        'name': line_name,
                    },
                )
            )

        move.with_context(check_move_validity=False).write({
            'invoice_line_ids': line_cmds,
            'bharat_arbitration_invoice': True,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': move.display_name,
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
