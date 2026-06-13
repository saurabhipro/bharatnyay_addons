# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .product_template import BHARAT_ARBITRATION_STAGE_SELECTION

STAGE_LINE_ORDER = tuple(code for code, _label in BHARAT_ARBITRATION_STAGE_SELECTION)


class AccountMove(models.Model):
    _inherit = 'account.move'

    bharat_arbitration_invoice = fields.Boolean(
        string='Arbitration billing invoice',
        index=True,
        help='Set when lines are built from BharatNyay loan batches / milestones.',
    )
    bharat_invoice_batch_ref = fields.Char(
        string='Batch no',
        index=True,
        help='Import/batch number shared by the cases billed on this invoice.',
    )
    bharat_loan_id = fields.Many2one(
        'bharat.loan',
        string='Loan case',
        index=True,
        ondelete='set null',
        copy=False,
        help='Legacy per-case invoice link. Consolidated invoices use annexure lines instead.',
    )
    bharat_loan_number = fields.Char(
        string='Loan number',
        related='bharat_loan_id.loan_number',
        store=True,
        readonly=True,
    )
    bharat_case_number = fields.Char(
        string='BharatNyay case no.',
        related='bharat_loan_id.case_number',
        store=True,
        readonly=True,
    )
    bharat_milestone_code = fields.Char(
        string='Milestone billed',
        index=True,
        copy=False,
        help='Workflow milestone billed on this consolidated invoice.',
    )
    bharat_annexure_line_ids = fields.One2many(
        'bharat.arbitration.invoice.annexure.line',
        'move_id',
        string='Annexure (case detail)',
        copy=False,
    )
    bharat_billing_event_ids = fields.One2many(
        'bharat.loan.billing.event',
        'move_id',
        string='Billing events',
        copy=False,
    )
    bharat_annexure_case_count = fields.Integer(
        string='Cases on annexure',
        compute='_compute_bharat_annexure_case_count',
    )

    @api.depends('bharat_annexure_line_ids')
    def _compute_bharat_annexure_case_count(self):
        for move in self:
            move.bharat_annexure_case_count = len(move.bharat_annexure_line_ids)

    def action_open_arbitration_line_loader(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft invoices can load arbitration lines.'))
        if self.move_type != 'out_invoice':
            raise UserError(_('Use customer invoices (out invoice).'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bill loan batch (consolidated)'),
            'res_model': 'bharat.arbitration.invoice.line.loader.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_print_arbitration_annexure(self):
        self.ensure_one()
        if not self.bharat_annexure_line_ids:
            raise UserError(_('This invoice has no annexure lines.'))
        report = self.env.ref(
            'bharatnyay_core.action_report_bharat_arbitration_invoice_annexure',
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_('Annexure report is not configured.'))
        return report.report_action(self)

    def _bharat_post_arbitration_invoice(self):
        """Confirm (post) a BharatNyay arbitration invoice."""
        for move in self:
            if move.state != 'draft':
                continue
            move.action_post()
        return self

    @api.model
    def _bharat_loan_case_line_label(self, loan):
        loan_no = (loan.loan_number or '').strip()
        bn_case = (loan.case_number or '').strip()
        if loan_no and bn_case and loan_no != bn_case:
            return '%s (%s)' % (loan_no, bn_case)
        return loan_no or bn_case or loan.display_name

    @api.model
    def _bharat_milestone_labels(self):
        return dict(BHARAT_ARBITRATION_STAGE_SELECTION)

    @api.model
    def bharat_create_consolidated_from_events(
        self, events, batch_names=None, milestone_codes=None, move=None,
    ):
        """Create or fill one consolidated customer invoice from pending billing events."""
        Event = self.env['bharat.loan.billing.event']
        events = events.filtered(lambda e: e.state == 'pending')
        if not events:
            raise UserError(_('No pending billing charges to invoice.'))

        companies = events.mapped('company_id')
        if len(companies) != 1:
            raise UserError(_('All cases in one invoice must belong to the same lender company.'))
        company = companies[0]
        partner = company.partner_id
        if not partner:
            raise UserError(
                _('Company “%s” has no linked partner for invoicing.') % company.display_name
            )

        labels = self._bharat_milestone_labels()
        batch_display = ', '.join(sorted({
            n for n in (batch_names or events.mapped('batch_number')) if (n or '').strip()
        })) or '-'
        milestone_set = sorted(set(milestone_codes or events.mapped('milestone_code')))

        groups = {}
        for event in events:
            key = (event.milestone_code, event.product_id.id, round(event.unit_price or 0.0, 2))
            groups.setdefault(key, Event.browse())
            groups[key] |= event

        def _stage_sort(item):
            code = item[0][0]
            return STAGE_LINE_ORDER.index(code) if code in STAGE_LINE_ORDER else 999

        line_cmds = []
        for (m_code, _prod_id, _price), group in sorted(groups.items(), key=_stage_sort):
            product = group[0].product_id
            if not product:
                raise UserError(_('Billing product missing on pending charge for %s.') % m_code)
            qty = len(group)
            unit_price = group[0].unit_price
            task_label = labels.get(m_code, m_code)
            line_name = _('%(task)s — %(count)s case(s)') % {'task': task_label, 'count': qty}
            if batch_display != '-':
                line_name = _('%(task)s — Batch %(batch)s — %(count)s case(s)') % {
                    'task': task_label,
                    'batch': batch_display,
                    'count': qty,
                }
            line_cmds.append((0, 0, {
                'product_id': product.id,
                'quantity': qty,
                'price_unit': unit_price,
                'name': line_name,
            }))

        if len(milestone_set) == 1:
            ref_task = labels.get(milestone_set[0], milestone_set[0])
        else:
            ref_task = _('Mixed stages')
        ref = _('BharatNyay batch %(batch)s — %(task)s') % {
            'batch': batch_display,
            'task': ref_task,
        }

        vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'company_id': company.id,
            'invoice_date': fields.Date.context_today(self),
            'ref': ref,
            'bharat_arbitration_invoice': True,
            'bharat_invoice_batch_ref': batch_display,
            'bharat_milestone_code': milestone_set[0] if len(milestone_set) == 1 else False,
            'invoice_line_ids': line_cmds,
        }

        if move:
            if move.state != 'draft' or move.move_type != 'out_invoice':
                raise UserError(_('Target invoice must be a draft customer invoice.'))
            move.with_context(check_move_validity=False).write({
                'partner_id': partner.id,
                'company_id': company.id,
                'ref': move.ref or vals['ref'],
                'bharat_arbitration_invoice': True,
                'bharat_invoice_batch_ref': batch_display,
                'bharat_milestone_code': vals['bharat_milestone_code'],
                'invoice_line_ids': [(5, 0, 0)] + line_cmds,
            })
            invoice = move
        else:
            invoice = self.create(vals)

        annexure_cmds = []
        seq = 10
        for event in events.sorted(key=lambda e: (e.batch_number or '', e.loan_number or '', e.id)):
            loan = event.loan_id
            annexure_cmds.append((0, 0, {
                'sequence': seq,
                'billing_event_id': event.id,
                'loan_id': loan.id,
                'loan_number': loan.loan_number,
                'case_number': loan.case_number,
                'customer_name': loan.customer_name,
                'milestone_code': event.milestone_code,
                'milestone_label': event.milestone_label,
                'product_id': event.product_id.id,
                'quantity': 1.0,
                'unit_price': event.unit_price,
            }))
            seq += 10

        invoice.with_context(check_move_validity=False).write({
            'bharat_annexure_line_ids': annexure_cmds,
        })

        annexure_by_event = {
            line.billing_event_id.id: line
            for line in invoice.bharat_annexure_line_ids
            if line.billing_event_id
        }
        for event in events:
            annexure_line = annexure_by_event.get(event.id)
            event.write({
                'state': 'invoiced',
                'move_id': invoice.id,
                'annexure_line_id': annexure_line.id if annexure_line else False,
            })

        invoice._bharat_post_arbitration_invoice()
        return invoice

    @api.model
    def bharat_prepare_arbitration_invoice_line_commands(self, loans, batch_display=''):
        """Legacy: aggregate lines by current bill stage (prefer consolidated wizard instead)."""
        Loan = self.env['bharat.loan']
        Template = self.env['product.template'].sudo()
        labels = self._bharat_milestone_labels()

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
            nums = [self._bharat_loan_case_line_label(loan) for loan in subset]
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
    def bharat_create_case_milestone_invoice(self, loan, milestone_code):
        """Legacy per-case invoice — not used when consolidated billing is enabled."""
        loan.ensure_one()
        billing_code = milestone_code
        if billing_code == 'commencement':
            return self.env['account.move']

        existing = self.search([
            ('bharat_arbitration_invoice', '=', True),
            ('bharat_loan_id', '=', loan.id),
            ('bharat_milestone_code', '=', billing_code),
            ('state', 'in', ('draft', 'posted')),
            ('move_type', '=', 'out_invoice'),
        ], limit=1)
        if existing:
            if existing.state == 'draft':
                existing._bharat_post_arbitration_invoice()
            return existing

        Template = self.env['product.template'].sudo()
        labels = self._bharat_milestone_labels()
        tmpl = Template.search([('bharat_arbitration_stage', '=', billing_code)], limit=2)
        if len(tmpl) != 1:
            raise UserError(
                _('Configure exactly one billing product for milestone “%s” (found %s).')
                % (labels.get(billing_code, billing_code), len(tmpl))
            )
        product = tmpl.product_variant_ids[:1]
        if not product:
            raise UserError(_('Product “%s” has no variant.') % tmpl.display_name)

        partner = loan.company_id.partner_id
        if not partner:
            raise UserError(
                _('Company “%s” has no linked partner for invoicing.') % loan.company_id.display_name
            )

        case_label = loan.bharat_invoice_reference_label()
        task_label = labels.get(billing_code, billing_code)
        line_name = _('%s — %s — batch %s') % (
            case_label,
            task_label,
            loan.batch_number or '-',
        )
        move = self.create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'company_id': loan.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'ref': _('BharatNyay — %s') % case_label,
            'bharat_arbitration_invoice': True,
            'bharat_invoice_batch_ref': loan.batch_number,
            'bharat_loan_id': loan.id,
            'bharat_milestone_code': billing_code,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'quantity': 1,
                'name': line_name,
            })],
        })
        move._bharat_post_arbitration_invoice()
        return move
