# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .product_template import BHARAT_ARBITRATION_STAGE_SELECTION
from .loan_milestone import POSTAL_BILLING_MILESTONE_CODES, POSTAL_BILLING_MILESTONE_NUMBERS

BILLABLE_MILESTONE_CODES = frozenset(
    code for code, _label in BHARAT_ARBITRATION_STAGE_SELECTION
)


class BharatLoanBatch(models.Model):
    _name = 'bharat.loan.batch'
    _description = 'Loan import batch'
    _rec_name = 'name'
    _order = 'name desc, id desc'

    name = fields.Char(string='Batch number', required=True, index=True)
    case_count = fields.Integer(compute='_compute_stats', string='Cases')
    company_ids = fields.Many2many(
        'res.company',
        compute='_compute_stats',
        string='Lenders',
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Batch number must be unique.'),
    ]

    @api.depends('name')
    def _compute_stats(self):
        Loan = self.env['bharat.loan'].sudo()
        for rec in self:
            loans = Loan.search([('batch_number', '=', rec.name)])
            rec.case_count = len(loans)
            rec.company_ids = loans.mapped('company_id')

    @api.model
    def _sync_from_loans(self):
        """Ensure one registry row per distinct loan batch_number."""
        Batch = self.sudo()
        self.env.cr.execute("""
            SELECT DISTINCT batch_number
            FROM bharat_loan
            WHERE batch_number IS NOT NULL AND batch_number != ''
        """)
        names = {row[0] for row in self.env.cr.fetchall()}
        existing = set(Batch.search([]).mapped('name'))
        Batch.create([{'name': name} for name in sorted(names - existing)])
        return True


class BharatLoanBillingEvent(models.Model):
    _name = 'bharat.loan.billing.event'
    _description = 'Pending / invoiced arbitration charge per case milestone'
    _order = 'accrual_date desc, id desc'

    loan_id = fields.Many2one(
        'bharat.loan',
        string='Case',
        required=True,
        ondelete='cascade',
        index=True,
    )
    batch_number = fields.Char(
        string='Batch',
        related='loan_id.batch_number',
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='loan_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    milestone_code = fields.Char(string='Milestone code', required=True, index=True)
    milestone_label = fields.Char(string='Milestone', required=True)
    accrual_date = fields.Datetime(
        string='Accrued on',
        default=fields.Datetime.now,
        required=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Pending invoice'),
            ('invoiced', 'Invoiced'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
    )
    product_id = fields.Many2one('product.product', string='Billing product', ondelete='restrict')
    unit_price = fields.Monetary(string='Rate per action', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    accrual_trigger = fields.Selection(
        [
            ('milestone_exit', 'Workflow milestone exit'),
            ('delivery', 'Postal delivery (POD)'),
        ],
        string='Accrual trigger',
        default='milestone_exit',
        required=True,
        index=True,
    )
    postal_dispatch_id = fields.Many2one(
        'bharat.loan.postal.dispatch',
        string='Postal dispatch',
        ondelete='set null',
        copy=False,
        index=True,
    )
    loan_number = fields.Char(related='loan_id.loan_number', store=True, readonly=True)
    case_number = fields.Char(related='loan_id.case_number', store=True, readonly=True)
    customer_name = fields.Char(related='loan_id.customer_name', readonly=True)

    _sql_constraints = [
        (
            'loan_milestone_uniq',
            'unique(loan_id, milestone_code)',
            'Each case can only accrue one billing event per milestone.',
        ),
    ]

    @api.model
    def _bharat_milestone_labels(self):
        return dict(BHARAT_ARBITRATION_STAGE_SELECTION)

    @api.model
    def _bharat_billing_product_for_milestone(self, milestone_code):
        Template = self.env['product.template'].sudo()
        labels = self._bharat_milestone_labels()
        tmpl = Template.search([('bharat_arbitration_stage', '=', milestone_code)], limit=2)
        if len(tmpl) != 1:
            raise UserError(
                _('Configure exactly one billing product for milestone “%s” (found %s).')
                % (labels.get(milestone_code, milestone_code), len(tmpl))
            )
        product = tmpl.product_variant_ids[:1]
        if not product:
            raise UserError(_('Product “%s” has no variant.') % tmpl.display_name)
        return product[0]

    @api.model
    def _bharat_unit_price_for_partner(self, product, partner, company):
        """Resolve unit price from partner pricelist (if available) or product list price."""
        date = fields.Date.context_today(self)
        pricelist = False
        if 'property_product_pricelist_id' in partner._fields:
            pricelist = partner.property_product_pricelist_id
        if pricelist:
            return pricelist._get_product_price(
                product,
                1.0,
                uom=product.uom_id,
                date=date,
            )
        return product.with_company(company).lst_price

    @api.model
    def bharat_accrue_for_loan(
        self, loan, milestone, accrual_trigger='milestone_exit', postal_dispatch=False,
    ):
        """Queue one pending billing row for a case milestone or postal delivery."""
        loan.ensure_one()
        code = milestone.code
        if code not in BILLABLE_MILESTONE_CODES:
            return self.browse()
        if code in POSTAL_BILLING_MILESTONE_CODES and accrual_trigger != 'delivery':
            # Notice 1 / Hearing 1 / Award bill only when POD status is billable.
            return self.browse()

        existing = self.search([
            ('loan_id', '=', loan.id),
            ('milestone_code', '=', code),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if existing:
            return existing

        partner = loan.company_id.partner_id
        if not partner:
            raise UserError(
                _('Company “%s” has no linked partner for billing.')
                % loan.company_id.display_name
            )

        product = self._bharat_billing_product_for_milestone(code)
        unit_price = self._bharat_unit_price_for_partner(product, partner, loan.company_id)
        labels = self._bharat_milestone_labels()
        accrual_dt = fields.Datetime.now()
        if postal_dispatch and postal_dispatch.delivery_date:
            accrual_dt = fields.Datetime.to_datetime(postal_dispatch.delivery_date)

        event = self.create({
            'loan_id': loan.id,
            'milestone_code': code,
            'milestone_label': labels.get(code, milestone.name or code),
            'product_id': product.id,
            'unit_price': unit_price,
            'currency_id': loan.company_id.currency_id.id,
            'state': 'pending',
            'accrual_trigger': accrual_trigger,
            'postal_dispatch_id': postal_dispatch.id if postal_dispatch else False,
            'accrual_date': accrual_dt,
        })
        if postal_dispatch:
            postal_dispatch.billing_event_id = event.id
        return event

    @api.model
    def bharat_accrue_for_postal_dispatch(self, dispatch):
        """Queue pending charge when a postal dispatch reaches a billable status."""
        dispatch.ensure_one()
        status = dispatch.post_office_status_id
        if not status or not status.triggers_billing:
            return self.browse()
        from .postal_dispatch import POSTAL_DOCUMENT_BILLING_CODE
        code = POSTAL_DOCUMENT_BILLING_CODE.get(dispatch.document_type or '', False)
        if not code or code not in BILLABLE_MILESTONE_CODES:
            return self.browse()
        Milestone = self.env['bharat.loan.milestone'].sudo()
        milestone = Milestone.search([('code', '=', code)], limit=1)
        if not milestone:
            milestone = Milestone.new({
                'code': code,
                'name': self._bharat_milestone_labels().get(code, code),
            })
        return self.bharat_accrue_for_loan(
            dispatch.loan_id,
            milestone,
            accrual_trigger='delivery',
            postal_dispatch=dispatch,
        )

    @api.model
    def _bharat_migrate_interim_order_billing_events(self):
        """Move legacy interim_order_1 billing rows into the hearing_1 pipeline bucket."""
        legacy = self.sudo().search([
            ('milestone_code', '=', 'interim_order_1'),
            ('state', '!=', 'cancelled'),
        ])
        if not legacy:
            return True
        labels = self._bharat_milestone_labels()
        Dispatch = self.env['bharat.loan.postal.dispatch'].sudo()
        for event in legacy:
            duplicate = self.search([
                ('loan_id', '=', event.loan_id.id),
                ('milestone_code', '=', 'hearing_1'),
                ('state', '!=', 'cancelled'),
                ('id', '!=', event.id),
            ], limit=1)
            if duplicate:
                if event.state == 'pending' and duplicate.state != 'pending':
                    event.unlink()
                continue
            event.write({
                'milestone_code': 'hearing_1',
                'milestone_label': labels.get('hearing_1', 'Hearing 1'),
            })
            dispatch = Dispatch.search([
                ('loan_id', '=', event.loan_id.id),
                ('document_type', '=', 'interim_order_1'),
            ], limit=1)
            if dispatch and not dispatch.billing_event_id:
                dispatch.billing_event_id = event.id
        return True

    @api.model
    def _bharat_backfill_hearing_postal_billing(self):
        """Accrue hearing charges for IO1 dispatches already marked delivered."""
        Dispatch = self.env['bharat.loan.postal.dispatch'].sudo()
        dispatches = Dispatch.search([
            ('document_type', '=', 'interim_order_1'),
            ('billing_event_id', '=', False),
        ]).filtered(lambda d: d._dispatch_pod_done())
        for dispatch in dispatches:
            try:
                self.bharat_accrue_for_postal_dispatch(dispatch)
            except UserError:
                continue
        return True

    @api.model
    def dashboard_pending_charges_pipeline(self, loan_ids=None):
        """Pending POD-stage charges for dashboard (Notice 1 → Hearing 1 → Award → Total)."""
        domain = [('state', '=', 'pending')]
        if loan_ids is not None:
            domain.append(('loan_id', 'in', loan_ids or [0]))
        events = self.sudo().search(domain)
        postal_codes = list(POSTAL_BILLING_MILESTONE_CODES)
        legacy_hearing_codes = frozenset({'hearing_1', 'interim_order_1'})

        Loan = self.env['bharat.loan'].sudo()
        Dispatch = self.env['bharat.loan.postal.dispatch'].sudo()
        loans = Loan.browse(loan_ids) if loan_ids is not None else Loan.search([])
        dispatch_map = {
            (dispatch.loan_id.id, dispatch.document_type): dispatch
            for dispatch in Dispatch.search([('loan_id', 'in', loans.ids)])
        }
        doc_for_code = {
            'notice_1': 'notice_1',
            'hearing_1': 'interim_order_1',
            'award': 'award',
        }

        specs = (
            ('notice_1', _('Notice 1'), '#3b82f6', 'fa-envelope-o'),
            ('hearing_1', _('Hearing 1'), '#8b5cf6', 'fa-video-camera'),
            ('award', _('Award'), '#ef4444', 'fa-trophy'),
        )
        stages = []
        for code, label, color, icon in specs:
            if code == 'hearing_1':
                stage_events = events.filtered(
                    lambda e: e.milestone_code in legacy_hearing_codes,
                )
                stage_domain = domain + [('milestone_code', 'in', list(legacy_hearing_codes))]
            else:
                stage_events = events.filtered(lambda e, c=code: e.milestone_code == c)
                stage_domain = domain + [('milestone_code', '=', code)]

            doc_type = doc_for_code[code]
            reached = Dispatch._dashboard_pod_milestone_reached_codes(code)
            pod_done = 0
            for loan in loans:
                if (loan.milestone_code or '') not in reached:
                    continue
                dispatch = dispatch_map.get((loan.id, doc_type))
                if dispatch and dispatch._dispatch_pod_done():
                    pod_done += 1

            case_count = len(stage_events.mapped('loan_id'))
            count = len(stage_events)
            stages.append({
                'key': code,
                'label': label,
                'billing_milestone_label': _('Milestone %s') % POSTAL_BILLING_MILESTONE_NUMBERS[code],
                'color': color,
                'icon': icon,
                'count': count,
                'cases': case_count,
                'amount': round(sum(stage_events.mapped('unit_price')), 2),
                'percent': round(100.0 * case_count / pod_done, 1) if pod_done else 0.0,
                'domain': stage_domain,
            })

        total_count = sum(stage['count'] for stage in stages)
        total_amount = round(sum(stage['amount'] for stage in stages), 2)
        pipeline_events = events.filtered(
            lambda e: e.milestone_code in POSTAL_BILLING_MILESTONE_CODES
            or e.milestone_code == 'interim_order_1',
        )

        return {
            'stages': stages,
            'total': {
                'key': 'total',
                'label': _('Total unbilled'),
                'count': total_count,
                'cases': len(pipeline_events.mapped('loan_id')),
                'amount': total_amount,
                'domain': domain + [
                    '|',
                    ('milestone_code', 'in', postal_codes),
                    ('milestone_code', '=', 'interim_order_1'),
                ],
            },
        }

    @api.model
    def bharat_search_pending(self, company_ids=None, batch_names=None, milestone_codes=None):
        """Pending charges filtered by admin selection (empty filter = all pending)."""
        domain = [('state', '=', 'pending')]
        if company_ids:
            domain.append(('company_id', 'in', company_ids))
        if batch_names:
            domain.append(('batch_number', 'in', list(batch_names)))
        if milestone_codes:
            domain.append(('milestone_code', 'in', list(milestone_codes)))
        return self.search(domain, order='batch_number, loan_number, case_number, id')
