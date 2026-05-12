# -*- coding: utf-8 -*-
"""Portfolio row aligned to the standard Excel import sheet (one record = one row)."""

from collections import defaultdict
import logging

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class BharatLoan(models.Model):
    _name = 'bharat.loan'
    _description = 'Loan portfolio (Excel import)'
    _order = 'loan_number, id'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'loan_number'

    loan_number = fields.Char(string='Loan Number', required=True, index=True)
    case_number = fields.Char(string='BharatNyay Case Number', copy=False, index=True, readonly=True, tracking=True)
    batch_number = fields.Char(string='Batch Number', copy=False, index=True, tracking=True)
    customer_name = fields.Char(string='Customer Name')

    # Keep master links for normalized future usage.
    region_id = fields.Many2one('bharat.region', string='Region (master)', index=True)
    borrower_state_id = fields.Many2one('bharat.borrower_state', string='State (master)', index=True)
    branch_id = fields.Many2one('bharat.branch', string='Branch (master)', index=True)
    location_id = fields.Many2one('bharat.loan_location', string='Location (master)')
    product_class_id = fields.Many2one('bharat.product_class', string='Product class (master)', index=True)
    writeoff_id = fields.Many2one('bharat.writeoff', string='Write off (master)', index=True)
    law_firm_id = fields.Many2one('bharat.law_firm', string='Law firm (master)')

    # Legacy text columns are kept as primary fields for compatibility with existing DB rows.
    branch = fields.Char(string='Branch')
    borrower_state = fields.Char(string='State')
    region = fields.Char(string='Region')
    location = fields.Char(string='Location')
    product_classification = fields.Char(string='Product classification')
    write_off = fields.Char(string='Write off')
    law_firm_name = fields.Char(string='Law firm name')

    followup_mode = fields.Char(string='Follow-up mode')
    follow_up_mode_alt = fields.Char(string='Follow-up mode (alt)')

    current_pos = fields.Monetary(
        string='Current POS',
        currency_field='currency_id',
    )

    lok_adalat_conciliation = fields.Char(string='Lok Adalat / Conciliation')
    lok_adalat_date = fields.Date(string='Lok Adalat / Conciliation Date')
    lok_adalat_location = fields.Char(string='Lok Adalat / Conciliation Location')
    lok_adalat_location_address = fields.Text(string='Lok Adalat / Conciliation Address')

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    financed_amount = fields.Monetary(string='Financed amount', currency_field='currency_id')
    disbursement_date = fields.Date(string='Date of disbursement')
    product = fields.Char(string='Product')
    collection_manager_name = fields.Char(string='Collection manager')
    collection_contact_phone = fields.Char(string='Contact no. (collection)')

    acm_name = fields.Char(string='ACM name')
    complete_assignment = fields.Char(string='Complete assignment')

    legal_fpr = fields.Monetary(string='Legal HPR/FPR', currency_field='currency_id')
    claim_amount = fields.Monetary(string='Claim amount', currency_field='currency_id')
    # Hero KPI strip — compact amounts (no currency symbol) for narrow tiles
    hero_financed_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Financed display',
    )
    hero_pos_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='POS display',
    )
    hero_claim_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Claim display',
    )
    hero_disburse_display = fields.Char(
        compute='_compute_hero_kpi_compact',
        string='Disbursed display',
    )
    notice_hand = fields.Char(string='Notice hand')
    notice_response_pdf = fields.Binary(string='Notice Response PDF', attachment=True)
    notice_response_pdf_filename = fields.Char(string='Notice Response Filename')
    pod = fields.Char(string='POD')
    deliver_date = fields.Date(string='Deliver date')
    deliver_status = fields.Char(string='Deliver status')

    WORKFLOW_STAGES = [
        ('commencement', 'Commencement'),
        ('notice', 'Notice'),
        ('appointment_of_arbitrator', 'Appointment of Arbitrator'),
        ('arbitrator_appointed', 'Arbitrator Appointed'),
        ('hearing', 'Hearing'),
        ('final_award', 'Final Arbitration Award'),
        ('paid', 'Paid'),
    ]
    WORKFLOW_STAGE_META = {
        'commencement': {'section': 1, 'phase': 'Commencement'},
        'notice': {'section': 21, 'phase': 'Notice'},
        'appointment_of_arbitrator': {'section': 11, 'phase': 'Appointment of Arbitrator'},
        'arbitrator_appointed': {'section': 11, 'phase': 'Arbitrator Appointed'},
        'hearing': {'section': 24, 'phase': 'Hearing'},
        'final_award': {'section': 31, 'phase': 'Final Arbitration Award'},
        'paid': {'section': 31, 'phase': 'Paid'},
    }

    # ── Dispute playbook / workflow ──────────────────────────────────────
    workflow_stage = fields.Selection(
        selection=WORKFLOW_STAGES,
        string='Workflow stage',
        default='notice',
        index=True,
        tracking=True,
        group_expand='_group_expand_workflow_stage',
    )
    workflow_stage_display = fields.Char(
        string='Workflow stage',
        compute='_compute_workflow_stage_display',
    )
    workflow_stage_index = fields.Integer(
        string='Workflow order',
        compute='_compute_workflow_stage_index',
        store=True,
    )
    workflow_section = fields.Integer(
        string='Workflow section',
        default=1,
        copy=False,
        help='Arbitration / dispute stage (1–31). Shown as the top timeline.',
    )
    workflow_phase = fields.Char(
        string='Current step label',
        default='Section 1 — Initiation',
        help='Displayed under the timeline (plain-language status).',
        tracking=True,
    )
    notice_line_ids = fields.One2many(
        'bharat.loan.notice.line',
        'loan_id',
        string='Notice history',
    )
    hearing_line_ids = fields.One2many(
        'bharat.loan.hearing.line',
        'loan_id',
        string='Hearing log',
    )
    interim_order_ids = fields.One2many(
        'bharat.loan.interim.order',
        'loan_id',
        string='Interim orders',
    )
    award_document_ids = fields.One2many(
        'bharat.loan.award.document',
        'loan_id',
        string='Award documents',
    )

    notice_count = fields.Integer(compute='_compute_case_activity_counts', string='# Notices')
    hearing_log_count = fields.Integer(compute='_compute_case_activity_counts', string='# Hearings')
    interim_order_count = fields.Integer(compute='_compute_case_activity_counts', string='# Interim orders')
    award_document_count = fields.Integer(compute='_compute_case_activity_counts', string='# Awards')

    borrower_email = fields.Char(string='Borrower email')
    borrower_phone = fields.Char(string='Borrower phone')
    borrower_address = fields.Text(string='Borrower address')

    respondent_name = fields.Char(string='Respondent entity')
    respondent_loan_reference = fields.Char(string='Respondent loan A/C')
    respondent_territory_display = fields.Char(
        string='Respondent geography',
        compute='_compute_respondent_territory_display',
    )

    arbitrator_id = fields.Many2one(
        'res.users',
        string='Arbitrator',
        tracking=True,
        index=True,
        domain=lambda self: self._domain_arbitrator_users(),
        help='Picked from users who have Arbitrator role in User roles.',
    )
    arbitrator_name = fields.Char(string='Arbitrator (text)', help='Legacy / import; synced when Arbitrator user is set.')
    arbitrator_email = fields.Char(string='Arbitrator email')
    arbitrator_handler = fields.Char(string='Arbitrator handler')

    hearing_datetime = fields.Datetime(
        string='Hearing date / time',
        tracking=True,
        help='Stored in UTC; invitations show the viewer’s timezone.',
    )
    hearing_video_url = fields.Char(
        string='Video meeting URL',
        tracking=True,
        help='Paste Teams, Zoom, Google Meet, or other join link.',
    )
    hearing_notes = fields.Text(
        string='Hearing instructions',
        help='Dial-in numbers, PIN, required documents — included in emailed invitations.',
    )
    hearing_link_type = fields.Selection(
        [
            ('external', 'External conferencing (Teams, Zoom, Meet, …)'),
            ('odoo', 'Odoo case link'),
        ],
        string='Meeting link type',
        default='external',
        tracking=True,
        help='External: paste a third-party video URL. Odoo case link: store a direct link to open this loan '
        'record in the Odoo web app (coordinate live video via Discuss or an external tool separately if needed).',
    )
    hearing_invite_user_ids = fields.Many2many(
        'res.users',
        'bharat_loan_hearing_invite_user_rel',
        'loan_id',
        'user_id',
        string='Also email (Odoo users)',
        help='These internal users receive the same hearing invitation by email (their user email address).',
    )
    interim_award_date = fields.Datetime(string='Interim award recorded on', copy=False)
    interim_award_notes = fields.Text(string='Interim award summary', copy=False)
    interim_award_amount = fields.Monetary(
        string='Interim amount (indicative)',
        currency_field='currency_id',
        copy=False,
    )

    case_dispute_notes = fields.Text(string='Dispute narrative')
    ai_classification_hint = fields.Char(string='Classification hint')
    ai_confidence_percent = fields.Float(
        string='Classification confidence %',
        digits=(5, 1),
        help='KPI hint (store 0–100).',
    )
    ai_manual_flags = fields.Integer(
        string='Review flags',
        default=0,
        help='Open issues / anomalies to review.',
    )

    def name_get(self):
        rows = []
        for rec in self:
            ln = rec.loan_number or ''
            cn = rec.case_number or ''
            nm = rec.customer_name or ''
            bits = []
            if ln:
                bits.append(ln)
            if cn and cn != ln:
                bits.append(_('case %s') % cn)
            label = ' — '.join(bits) if bits else (_('Loan %s') % rec.id)
            if nm:
                label = '%s (%s)' % (label, nm)
            rows.append((rec.id, label))
        return rows

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100, order=None):
        """Loan rows have no ``name`` field; search omnibox + M2Os match several references."""
        args = list(args or [])
        if not (name or '').strip():
            return super().name_search(name, args=args, operator=operator, limit=limit, order=order)
        or_domain = expression.OR(
            [
                [('loan_number', operator, name)],
                [('case_number', operator, name)],
                [('batch_number', operator, name)],
                [('customer_name', operator, name)],
                [('respondent_loan_reference', operator, name)],
                [('borrower_phone', operator, name)],
                [('borrower_email', operator, name)],
            ]
        )
        domain = expression.AND([args, or_domain])
        records = self.search(domain, limit=limit, order=order)
        return records.name_get()
    dossier_file_count = fields.Integer(
        string='Dossier files',
        default=0,
        help='Rough doc-pack count shown on the KPI strip.',
    )

    @api.depends('branch_id', 'branch', 'borrower_state_id', 'borrower_state')
    def _compute_respondent_territory_display(self):
        for rec in self:
            parts = []
            if rec.branch_id:
                parts.append(rec.branch_id.name)
            elif rec.branch:
                parts.append(rec.branch)
            if rec.borrower_state_id:
                parts.append(rec.borrower_state_id.name)
            elif rec.borrower_state:
                parts.append(rec.borrower_state)
            rec.respondent_territory_display = ', '.join(p for p in parts if p)

    @api.depends('workflow_stage')
    def _compute_workflow_stage_index(self):
        order = {key: idx for idx, (key, _) in enumerate(self.WORKFLOW_STAGES, start=1)}
        for rec in self:
            rec.workflow_stage_index = order.get(rec.workflow_stage or '', 1)

    @api.depends('workflow_stage')
    def _compute_workflow_stage_display(self):
        labels = dict(self.WORKFLOW_STAGES)
        icons = {
            'commencement': '🚀',
            'notice': '📩',
            'appointment_of_arbitrator': '👤',
            'arbitrator_appointed': '✅',
            'hearing': '🎥',
            'final_award': '⚖️',
            'paid': '💰',
        }
        for rec in self:
            stage = rec.workflow_stage or ''
            label = labels.get(stage, stage or 'Unknown')
            ico = icons.get(stage, '•')
            rec.workflow_stage_display = f'{ico} {label}'

    @staticmethod
    def _format_amount_compact(amount):
        """Format monetary value without symbol: 150000 -> 150K (for narrow hero tiles)."""
        if amount in (None, False):
            return '—'
        try:
            n = float(amount)
        except (TypeError, ValueError):
            return '—'
        if abs(n) < 1e-9:
            return '0'
        sign = '-' if n < 0 else ''
        x = abs(n)

        def tier(div, suffix):
            v = x / div
            if v >= 100:
                t = '%.0f' % v
            elif v >= 10:
                t = ('%.1f' % v).rstrip('0').rstrip('.')
            else:
                t = ('%.1f' % v).rstrip('0').rstrip('.')
            return f'{sign}{t}{suffix}'

        if x >= 1_000_000_000:
            return tier(1_000_000_000, 'B')
        if x >= 1_000_000:
            return tier(1_000_000, 'M')
        if x >= 1000:
            return tier(1000, 'K')
        return f'{sign}{round(x)}'

    @api.depends('financed_amount', 'current_pos', 'claim_amount', 'disbursement_date')
    def _compute_hero_kpi_compact(self):
        for rec in self:
            rec.hero_financed_display = self._format_amount_compact(rec.financed_amount)
            rec.hero_pos_display = self._format_amount_compact(rec.current_pos)
            rec.hero_claim_display = self._format_amount_compact(rec.claim_amount)
            d = rec.disbursement_date
            if not d:
                rec.hero_disburse_display = '—'
            else:
                rec.hero_disburse_display = d.strftime('%d %b %y')

    @api.model
    def _group_expand_workflow_stage(self, stages, domain):
        """Kanban/read_group: show every workflow stage column even when empty."""
        return [key for key, _label in self.WORKFLOW_STAGES]

    @api.model
    def _domain_arbitrator_users(self):
        """Users listed as arbitrator in BharatNyay role assignments (active)."""
        Assignment = self.env['bharat.user.role.assignment'].sudo()
        assigns = Assignment.search([('role', '=', 'arbitrator'), ('active', '=', True)])
        uids = assigns.mapped('user_id').filtered(lambda u: u.active).ids
        if uids:
            return [('id', 'in', uids)]
        return [('share', '=', False)]

    @staticmethod
    def _apply_arbitrator_user_to_vals(env, vals):
        """Keep legacy text fields aligned when arbitrator_id is set/cleared."""
        if 'arbitrator_id' not in vals:
            return
        arb = vals['arbitrator_id']
        if not arb:
            vals.setdefault('arbitrator_name', False)
            vals.setdefault('arbitrator_email', False)
            return
        user = env['res.users'].browse(arb)
        if user:
            vals['arbitrator_name'] = user.name
            vals['arbitrator_email'] = user.email or ''

    @api.onchange('arbitrator_id')
    def _onchange_arbitrator_id(self):
        for rec in self:
            if rec.arbitrator_id:
                rec.arbitrator_name = rec.arbitrator_id.name
                rec.arbitrator_email = rec.arbitrator_id.email or ''

    @api.constrains('workflow_section')
    def _check_workflow_section(self):
        for rec in self:
            sec = rec.workflow_section
            if sec is False or sec is None:
                continue
            if sec < 1 or sec > 31:
                raise ValidationError(_("Workflow section must be between 1 and 31."))

    @api.onchange('workflow_stage')
    def _onchange_workflow_stage(self):
        for rec in self:
            stage = rec.workflow_stage
            if not stage:
                continue
            meta = self.WORKFLOW_STAGE_META.get(stage, {})
            if meta.get('section'):
                rec.workflow_section = meta['section']
            if meta.get('phase'):
                rec.workflow_phase = meta['phase']

    @api.onchange('workflow_section')
    def _onchange_workflow_section(self):
        order_keys = [key for key, _ in self.WORKFLOW_STAGES]
        for rec in self:
            section = rec.workflow_section or 1
            best = order_keys[0]
            best_delta = 10**9
            for key in order_keys:
                sec = self.WORKFLOW_STAGE_META.get(key, {}).get('section', 1)
                delta = abs(sec - section)
                if delta < best_delta:
                    best = key
                    best_delta = delta
            rec.workflow_stage = best

    @api.model
    def _normalize_workflow_values(self, vals):
        stage = vals.get('workflow_stage')
        if stage:
            meta = self.WORKFLOW_STAGE_META.get(stage, {})
            vals.setdefault('workflow_section', meta.get('section', 1))
            vals.setdefault('workflow_phase', meta.get('phase', ''))
            return
        section = vals.get('workflow_section')
        if section is None:
            return
        order_keys = [key for key, _ in self.WORKFLOW_STAGES]
        best = order_keys[0]
        best_delta = 10**9
        for key in order_keys:
            sec = self.WORKFLOW_STAGE_META.get(key, {}).get('section', 1)
            delta = abs(sec - section)
            if delta < best_delta:
                best = key
                best_delta = delta
        vals.setdefault('workflow_stage', best)
        vals.setdefault('workflow_phase', self.WORKFLOW_STAGE_META.get(best, {}).get('phase', ''))

    @api.depends(
        'notice_line_ids',
        'hearing_line_ids',
        'interim_order_ids',
        'award_document_ids',
    )
    def _compute_case_activity_counts(self):
        for rec in self:
            rec.notice_count = len(rec.notice_line_ids)
            rec.hearing_log_count = len(rec.hearing_line_ids)
            rec.interim_order_count = len(rec.interim_order_ids)
            rec.award_document_count = len(rec.award_document_ids)

    def action_open_notice_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Notice history'),
            'res_model': 'bharat.loan.notice.line',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_hearing_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hearings'),
            'res_model': 'bharat.loan.hearing.line',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_interim_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interim orders'),
            'res_model': 'bharat.loan.interim.order',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def action_open_award_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Awards'),
            'res_model': 'bharat.loan.award.document',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
        }

    def _action_open_notice_wizard(self, notice_type, notice_number=False):
        self.ensure_one()
        names = {'notice': 'Notice'}
        next_num = notice_number or ((max(self.notice_line_ids.mapped('notice_number') or [0]) + 1) or 1)
        return {
            'type': 'ir.actions.act_window',
            'name': f"Send {names.get(notice_type, 'Notice')}",
            'res_model': 'bharat.loan.notice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'default_notice_type': notice_type,
                'default_notice_number': next_num,
            },
        }

    def action_send_notice_1(self):
        return self._action_open_notice_wizard('notice', notice_number=1)

    def action_send_notice_2(self):
        return self._action_open_notice_wizard('notice', notice_number=2)

    def action_send_notice_3(self):
        return self._action_open_notice_wizard('notice', notice_number=3)

    def action_send_notice(self):
        return self._action_open_notice_wizard('notice')

    def _hearing_build_odoo_case_url(self):
        self.ensure_one()
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        if not base:
            return ''
        cid = self.env.company.id
        act = self.env.ref('bharatnyay_core.action_bharat_loan', raise_if_not_found=False)
        slug = (act.path or '').strip().lower() if act else ''
        if slug:
            # Odoo 17+ web client routes: /odoo/<action.path>/<record_id> (path must NOT contain '.').
            return '%s/odoo/%s/%s?cids=%s' % (base, slug, self.id, cid)
        # Fallback before action.path is upgraded in DB
        return '%s/web#id=%s&model=bharat.loan&view_type=form&cids=%s' % (base, self.id, cid)

    @staticmethod
    def _hearing_normalize_external_meeting_url(url):
        u = (url or '').strip()
        if not u:
            return ''
        low = u.lower()
        if low.startswith(('http://', 'https://')):
            return u
        if u.startswith('/'):
            return u
        if '://' in u:
            return u
        return 'https://%s' % u

    def action_appoint_arbitrator(self):
        for rec in self:
            if not rec.arbitrator_id and not (rec.arbitrator_name or '').strip():
                raise UserError(_("Please select an arbitrator user (or enter a name)."))
            arb_label = (
                rec.arbitrator_id.name
                if rec.arbitrator_id
                else (rec.arbitrator_name or '').strip()
            )
            rec.write({
                'workflow_stage': 'arbitrator_appointed',
                'workflow_phase': 'Arbitrator Appointed',
            })
            rec.message_post(
                body=_("Arbitrator appointed: <b>%s</b>") % (arb_label,),
            )
        return True

    def action_schedule_hearing(self):
        self.ensure_one()
        if self.workflow_stage == 'hearing':
            raise UserError(
                _('This case is already at Hearing. Use the Hearing tab to change date, link, or notes.')
            )
        if self.workflow_stage != 'arbitrator_appointed':
            stages = dict(self._fields['workflow_stage'].selection)
            raise UserError(
                _('Schedule Hearing is only available when the arbitrator has been appointed.')
                + ' '
                + _('Current workflow stage is: %s')
                % stages.get(self.workflow_stage, self.workflow_stage or '?')
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Hearing'),
            'res_model': 'bharat.loan.hearing.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def _hearing_invitation_html(self):
        self.ensure_one()
        when = ''
        if self.hearing_datetime:
            local = fields.Datetime.context_timestamp(self, self.hearing_datetime)
            when = str(local)
        case_ref = self.case_number or self.loan_number or ''
        nm = escape(self.loan_number or '')
        cust = escape(self.customer_name or '')
        parts = [
            '<p>%s</p>' % escape(_('You are invited to the arbitration hearing.')),
            '<p><b>%s</b> %s<br/><b>%s</b> %s / %s</p>'
            % (
                escape(_('Case:')),
                escape(case_ref),
                escape(_('Loan / borrower:')),
                nm,
                cust,
            ),
            '<p><b>%s</b> %s</p>'
            % (
                escape(_('When (reference):')),
                escape(when or _('Not set')),
            ),
        ]
        url = (self.hearing_video_url or '').strip()
        if self.hearing_link_type == 'odoo':
            link_intro = escape(_('Open this case in Odoo (bookmark or click):'))
        else:
            link_intro = escape(_('Join online (video / conference):'))
        parts.append(
            '<p><b>%s</b><br/><a href="%s">%s</a></p>'
            % (
                link_intro,
                escape(url),
                escape(url) if url else escape(_('(not set)')),
            )
        )
        if self.hearing_notes:
            parts.append(
                '<p><b>%s</b><br/>%s</p>'
                % (
                    escape(_('Instructions:')),
                    escape(self.hearing_notes).replace('\n', '<br/>'),
                )
            )
        return ''.join(parts)

    def action_send_hearing_video_link(self):
        for rec in self:
            if rec.workflow_stage != 'hearing':
                raise UserError(
                    _('Send video link only when the case is in the Hearing stage.')
                )
            if not rec.hearing_datetime:
                raise UserError(_('Set a hearing date and time before sending invitations.'))
            url = (rec.hearing_video_url or '').strip()
            if rec.hearing_link_type == 'odoo':
                canonical = (rec._hearing_build_odoo_case_url() or '').strip()
                if canonical:
                    url = canonical
                    rec.sudo().write({'hearing_video_url': canonical})
            if not url:
                raise UserError(
                    _('Add a meeting link on the Hearing tab. For Odoo links, set `web.base.url` '
                      'and upgrade BharatNyay Core so the Loan sheet action exposes a URL path.')
                )

            body_html = rec._hearing_invitation_html()
            case_ref = rec.case_number or rec.loan_number or 'loan'
            subject = _('Hearing link — %s') % case_ref

            Mail = rec.env['mail.mail'].sudo()
            sent_labels = []
            seen_mail = set()

            borrower = (rec.borrower_email or '').strip()
            if borrower:
                key_b = borrower.lower()
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': borrower,
                    'auto_delete': True,
                }).send()
                sent_labels.append(_('borrower'))
                seen_mail.add(key_b)

            arb_mail = ''
            if rec.arbitrator_id and rec.arbitrator_id.email:
                arb_mail = rec.arbitrator_id.email.strip()
            elif rec.arbitrator_email:
                arb_mail = rec.arbitrator_email.strip()
            if arb_mail and arb_mail.lower() not in seen_mail:
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': arb_mail,
                    'auto_delete': True,
                }).send()
                sent_labels.append(_('arbitrator'))
                seen_mail.add(arb_mail.lower())

            for usr in rec.hearing_invite_user_ids:
                em = (usr.email or '').strip() or (usr.partner_id.email or '').strip()
                if not em:
                    continue
                key = em.lower()
                if key in seen_mail:
                    continue
                Mail.create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': em,
                    'auto_delete': True,
                }).send()
                seen_mail.add(key)
                disp = usr.name or usr.login or em
                sent_labels.append(disp)

            if not sent_labels:
                raise UserError(
                    _(
                        'Add a borrower email or arbitrator email, or choose one or more Odoo users '
                        'under “Also email (Odoo users)” on the Hearing tab so invitations have recipients.'
                    )
                )

            rec.message_post(
                body=_('Video meeting invitation sent to: %s') % ', '.join(sent_labels),
            )
        return True

    def action_join_hearing_meeting(self):
        """Open meeting join target in a new browser tab (never duplicate this form dialog)."""
        self.ensure_one()
        if self.workflow_stage != 'hearing':
            raise UserError(_('Join online is available during the Hearing stage.'))

        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        mode = self.hearing_link_type or 'external'

        if mode == 'odoo':
            # Always rebuild — old links used invalid path segments such as ``bharat.loan``.
            jump = (self._hearing_build_odoo_case_url() or '').strip()
        else:
            raw = (self.hearing_video_url or '').strip()
            jump = self._hearing_normalize_external_meeting_url(raw).strip()
            if jump.startswith('/') and base:
                jump = base + jump

        if not jump:
            raise UserError(_('No video meeting URL is set. Add one on the Hearing tab or reschedule.'))

        if not jump.lower().startswith(('http://', 'https://')):
            raise UserError(
                _('Could not resolve a valid meeting URL. For external links include the full '
                  'address (e.g. https://meet.google.com/…); for Odoo links upgrade BharatNyay Core '
                  '(Loan sheet action must define a URL path), and ensure `web.base.url` is set.')
            )

        return {'type': 'ir.actions.act_url', 'url': jump, 'target': 'new'}

    def action_pass_interim_award(self):
        self.ensure_one()
        if self.workflow_stage != 'hearing':
            raise UserError(_('Pass Interim Award is only available during the Hearing stage.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pass Interim Award'),
            'res_model': 'bharat.loan.interim.award.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    @api.model
    def _ensure_master(self, model_name, name, extra_vals=None):
        """Get-or-create helper for master records from imported text."""
        if not name:
            return False
        value = str(name).strip()
        if not value:
            return False
        Model = self.env[model_name]
        rec = Model.search([('name', '=ilike', value)], limit=1)
        if rec:
            if extra_vals:
                to_write = {k: v for k, v in extra_vals.items() if v and not rec[k]}
                if to_write:
                    rec.write(to_write)
            return rec
        vals = {'name': value}
        if extra_vals:
            vals.update({k: v for k, v in extra_vals.items() if v})
        return Model.create(vals)

    @api.model
    def _coerce_many2one_name_strings(self, vals):
        """Resolve plain name strings mistakenly mapped to *_id columns (import edge cases)."""
        spec = (
            ('region_id', 'bharat.region', 'region'),
            ('borrower_state_id', 'bharat.borrower_state', 'borrower_state'),
            ('branch_id', 'bharat.branch', 'branch'),
            ('location_id', 'bharat.loan_location', 'location'),
            ('product_class_id', 'bharat.product_class', 'product_classification'),
            ('writeoff_id', 'bharat.writeoff', 'write_off'),
            ('law_firm_id', 'bharat.law_firm', 'law_firm_name'),
        )
        for m2o_fname, model_name, text_fname in spec:
            raw = vals.get(m2o_fname)
            if not isinstance(raw, str):
                continue
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.isdigit():
                vals[m2o_fname] = int(stripped)
                continue
            rec = self._ensure_master(model_name, stripped)
            if rec:
                vals[m2o_fname] = rec.id
                vals.setdefault(text_fname, stripped)

    @api.model
    def _populate_master_links_from_text(self, vals):
        """During import/create/write, map text columns to Many2one master IDs."""
        region = self._ensure_master('bharat.region', vals.get('region')) if vals.get('region') else False
        if region and not vals.get('region_id'):
            vals['region_id'] = region.id

        state = self._ensure_master(
            'bharat.borrower_state',
            vals.get('borrower_state'),
            {'region_id': vals.get('region_id')},
        ) if vals.get('borrower_state') else False
        if state and not vals.get('borrower_state_id'):
            vals['borrower_state_id'] = state.id
        if state and state.region_id and not vals.get('region_id'):
            vals['region_id'] = state.region_id.id

        branch = self._ensure_master(
            'bharat.branch',
            vals.get('branch'),
            {
                'region_id': vals.get('region_id'),
                'borrower_state_id': vals.get('borrower_state_id'),
            },
        ) if vals.get('branch') else False
        if branch and not vals.get('branch_id'):
            vals['branch_id'] = branch.id
        if branch and branch.region_id and not vals.get('region_id'):
            vals['region_id'] = branch.region_id.id
        if branch and branch.borrower_state_id and not vals.get('borrower_state_id'):
            vals['borrower_state_id'] = branch.borrower_state_id.id

        location = self._ensure_master(
            'bharat.loan_location',
            vals.get('location'),
            {'branch_id': vals.get('branch_id')},
        ) if vals.get('location') else False
        if location and not vals.get('location_id'):
            vals['location_id'] = location.id

        if vals.get('product_classification') and not vals.get('product_class_id'):
            pclass = self._ensure_master('bharat.product_class', vals.get('product_classification'))
            if pclass:
                vals['product_class_id'] = pclass.id

        if vals.get('write_off') and not vals.get('writeoff_id'):
            wr = self._ensure_master('bharat.writeoff', vals.get('write_off'))
            if wr:
                vals['writeoff_id'] = wr.id

        if vals.get('law_firm_name') and not vals.get('law_firm_id'):
            firm = self._ensure_master('bharat.law_firm', vals.get('law_firm_name'))
            if firm:
                vals['law_firm_id'] = firm.id

    @api.model
    def _populate_text_from_master_links(self, vals):
        """Keep legacy text columns in sync when import uses Many2one columns."""
        if vals.get('region_id') and not vals.get('region'):
            vals['region'] = self.env['bharat.region'].browse(vals['region_id']).name
        if vals.get('borrower_state_id') and not vals.get('borrower_state'):
            vals['borrower_state'] = self.env['bharat.borrower_state'].browse(vals['borrower_state_id']).name
        if vals.get('branch_id') and not vals.get('branch'):
            vals['branch'] = self.env['bharat.branch'].browse(vals['branch_id']).name
        if vals.get('location_id') and not vals.get('location'):
            vals['location'] = self.env['bharat.loan_location'].browse(vals['location_id']).name
        if vals.get('product_class_id') and not vals.get('product_classification'):
            vals['product_classification'] = self.env['bharat.product_class'].browse(vals['product_class_id']).name
        if vals.get('writeoff_id') and not vals.get('write_off'):
            vals['write_off'] = self.env['bharat.writeoff'].browse(vals['writeoff_id']).name
        if vals.get('law_firm_id') and not vals.get('law_firm_name'):
            vals['law_firm_name'] = self.env['bharat.law_firm'].browse(vals['law_firm_id']).name

    @api.model_create_multi
    def create(self, vals_list):
        is_import = bool(self.env.context.get('import_file') or self.env.context.get('from_import'))
        shared_batch_number = False
        if is_import and any(not vals.get('batch_number') for vals in vals_list):
            shared_batch_number = self.env['ir.sequence'].next_by_code('bharat.loan.import.batch') or 'Batch 1'

        normalized = []
        for vals in vals_list:
            values = dict(vals)
            self._apply_arbitrator_user_to_vals(self.env, values)
            if not values.get('case_number'):
                values['case_number'] = self.env['ir.sequence'].next_by_code('bharat.loan.case.number') or '/'
            if shared_batch_number and not values.get('batch_number'):
                values['batch_number'] = shared_batch_number
            self._normalize_workflow_values(values)
            self._coerce_many2one_name_strings(values)
            self._populate_master_links_from_text(values)
            self._populate_text_from_master_links(values)
            normalized.append(values)
        return super().create(normalized)

    def write(self, vals):
        values = dict(vals)
        self._apply_arbitrator_user_to_vals(self.env, values)
        self._normalize_workflow_values(values)
        self._coerce_many2one_name_strings(values)
        self._populate_master_links_from_text(values)
        self._populate_text_from_master_links(values)
        return super().write(values)

    @api.onchange('branch_id')
    def _onchange_branch(self):
        for rec in self:
            branch = rec.branch_id
            if not branch:
                continue
            rec.branch = branch.name
            if branch.region_id:
                rec.region_id = branch.region_id
                rec.region = branch.region_id.name
            if branch.borrower_state_id:
                rec.borrower_state_id = branch.borrower_state_id
                rec.borrower_state = branch.borrower_state_id.name

    @api.onchange('borrower_state_id')
    def _onchange_borrower_state(self):
        for rec in self:
            st = rec.borrower_state_id
            if (
                st
                and st.region_id
                and (not rec.region_id or rec.region_id == st.region_id)
            ):
                rec.region_id = st.region_id
            if st:
                rec.borrower_state = st.name
                if st.region_id:
                    rec.region = st.region_id.name

    @api.onchange('location_id')
    def _onchange_location(self):
        for rec in self:
            loc = rec.location_id
            if not loc or not loc.branch_id:
                continue
            rec.location = loc.name
            rec.branch_id = loc.branch_id
            b = loc.branch_id
            rec.branch = b.name
            if b.region_id:
                rec.region_id = b.region_id
                rec.region = b.region_id.name
            if b.borrower_state_id:
                rec.borrower_state_id = b.borrower_state_id
                rec.borrower_state = b.borrower_state_id.name

    @api.onchange('region_id', 'product_class_id', 'writeoff_id', 'law_firm_id')
    def _onchange_master_labels(self):
        for rec in self:
            if rec.region_id:
                rec.region = rec.region_id.name
            if rec.product_class_id:
                rec.product_classification = rec.product_class_id.name
            if rec.writeoff_id:
                rec.write_off = rec.writeoff_id.name
            if rec.law_firm_id:
                rec.law_firm_name = rec.law_firm_id.name

    @api.model
    def get_dashboard_statistics(self):
        """Aggregates for BharatNyay OWL dashboard (JSON-serializable)."""
        self.check_access('read')
        Currency = self.env.company.currency_id
        rows = self.search_read(
            [],
            [
                'loan_number',
                'customer_name',
                'workflow_stage',
                'branch_id',
                'product_class_id',
                'product_classification',
                'product',
                'writeoff_id',
                'current_pos',
                'claim_amount',
                'disbursement_date',
                'create_date',
                'deliver_status',
                'lok_adalat_date',
            ],
            order='create_date desc',
            limit=100000,
        )

        total = len(rows)
        total_pos = 0.0
        total_claim = 0.0
        borrower_keys = set()
        active_followup = 0
        lok_done = 0

        monthly_created = defaultdict(int)
        monthly_claim = defaultdict(float)
        by_branch = defaultdict(lambda: {'total': 0, 'active_pos': 0, 'pos_sum': 0.0, 'claim_sum': 0.0})
        by_product_label = defaultdict(int)
        by_stage = defaultdict(int)

        for row in rows:
            pos_val = row.get('current_pos') or 0.0
            try:
                pos_f = float(pos_val)
            except (TypeError, ValueError):
                pos_f = 0.0
            total_pos += pos_f

            claim_val = row.get('claim_amount') or 0.0
            try:
                claim_f = float(claim_val)
            except (TypeError, ValueError):
                claim_f = 0.0
            total_claim += claim_f

            cname = (row.get('customer_name') or '').strip()
            borrower_keys.add((cname or '').lower() or '_blank_')

            if pos_f > 0:
                active_followup += 1
            dsl = row.get('deliver_status')
            dsl_l = dsl.lower().strip() if isinstance(dsl, str) else ''
            delivered = dsl_l in ('delivered', 'yes', 'done', 'y', 'completed')
            if delivered or row.get('lok_adalat_date'):
                lok_done += 1

            stage_key = row.get('workflow_stage') or ''
            if stage_key:
                by_stage[stage_key] += 1

            cdate = row.get('create_date')
            bucket = None
            if hasattr(cdate, 'strftime'):
                bucket = cdate.strftime('%Y-%m')
            elif isinstance(cdate, str) and len(cdate) >= 7:
                bucket = cdate[:7]
            if bucket:
                monthly_created[bucket] += 1
                monthly_claim[bucket] += claim_f

            bik = row.get('branch_id')
            if bik:
                bid, bname = bik[0], bik[1]
            else:
                bid, bname = None, 'Unassigned branch'
            bkey = bid if bid is not None else -1
            by_branch[bkey]['total'] += 1
            by_branch[bkey]['branch_name'] = bname
            by_branch[bkey]['pos_sum'] += pos_f
            by_branch[bkey]['claim_sum'] += claim_f
            if pos_f > 0:
                by_branch[bkey]['active_pos'] += 1

            pcid = row.get('product_class_id')
            pcl = pcid[1] if pcid else None
            if not pcl:
                pcl = row.get('product_classification') or row.get('product') or 'Unclassified'
            by_product_label[pcl] += 1

        uniq_borrowers = len(borrower_keys)

        month_keys = sorted(set(monthly_created.keys()) | set(monthly_claim.keys()))[-18:]
        monthly_series = [
            {
                'period': mk,
                'count': monthly_created.get(mk, 0),
                'claim_sum': round(monthly_claim.get(mk, 0.0), 2),
            }
            for mk in month_keys
        ]

        palette = ('#6366f1', '#06b6d4', '#8b5cf6', '#22c55e', '#eab308',
                   '#ef4444', '#f97316', '#64748b', '#14b8a6', '#a855f7')
        prod_items = sorted(by_product_label.items(), key=lambda x: -x[1])
        denom = sum(by_product_label.values()) or 1
        pie = []
        for i, (label, cnt) in enumerate(prod_items[:10]):
            pie.append({
                'label': label,
                'count': cnt,
                'percent': round(100.0 * cnt / denom, 2),
                'color': palette[i % len(palette)],
            })
        other = sum(c for _, c in prod_items[10:])
        if other:
            pie.append({
                'label': 'Other',
                'count': other,
                'percent': round(100.0 * other / denom, 2),
                'color': '#94a3b8',
            })

        branches_sorted = sorted(
            by_branch.items(),
            key=lambda kv: kv[1]['total'],
            reverse=True,
        )[:16]

        entity_cards = []
        for _, agg in branches_sorted:
            t = agg['total']
            a = agg['active_pos']
            entity_cards.append({
                'title': agg.get('branch_name') or 'Branch',
                'subtitle': '',
                'total': t,
                'active_exposure': a,
                'settled_hint': max(0, t - a),
                'pos_amount': agg['pos_sum'],
                'claim_amount': agg['claim_sum'],
            })

        stage_label_map = dict(self.WORKFLOW_STAGES)
        stage_style = {
            'commencement': {'color': '#6366f1', 'icon': 'fa-flag-checkered'},
            'notice': {'color': '#0ea5e9', 'icon': 'fa-envelope-open-o'},
            'appointment_of_arbitrator': {'color': '#f59e0b', 'icon': 'fa-user-plus'},
            'arbitrator_appointed': {'color': '#8b5cf6', 'icon': 'fa-user-circle-o'},
            'hearing': {'color': '#10b981', 'icon': 'fa-video-camera'},
            'final_award': {'color': '#ef4444', 'icon': 'fa-gavel'},
            'paid': {'color': '#22c55e', 'icon': 'fa-check-circle-o'},
        }
        stage_cards = []
        for stage_key, stage_label in self.WORKFLOW_STAGES:
            cnt = by_stage.get(stage_key, 0)
            sty = stage_style.get(stage_key, {})
            stage_cards.append({
                'key': stage_key,
                'label': stage_label or stage_label_map.get(stage_key) or stage_key,
                'count': cnt,
                'percent': round((100.0 * cnt / total), 1) if total else 0.0,
                'color': sty.get('color', '#64748b'),
                'icon': sty.get('icon', 'fa-circle-o'),
            })

        pos_ratio = round(100 * active_followup / total, 1) if total else 0.0

        return {
            'currency_id': Currency.id,
            'currency_symbol': Currency.symbol or '₹',
            'decimals': Currency.decimal_places,
            'kpis': {
                'total_loans': total,
                'active_exposure_rows': active_followup,
                'delivered_or_lok': lok_done,
                'pos_ratio_pct': pos_ratio,
                'unique_customers': uniq_borrowers,
                'total_pos_amount': round(total_pos, 2),
                'total_claim_amount': round(total_claim, 2),
            },
            'monthly_created': monthly_series,
            'product_mix': pie,
            'entity_cards': entity_cards,
            'stage_cards': stage_cards,
        }

    def _register_hook(self):
        super()._register_hook()
        try:
            from odoo.addons.bharatnyay_core.hooks import (
                repair_loan_arbitrator_id_column,
                repair_loan_foreign_key_columns,
                repair_loan_hearing_columns,
                seed_bharatnyay_demo_users_and_roles,
            )
        except ImportError:
            return
        if not getattr(self.pool, 'db_name', False):
            return
        cr = self.pool.cursor()
        try:
            # Normalize legacy workflow values to consolidated steps.
            cr.execute(
                """
                UPDATE bharat_loan
                SET workflow_stage = 'notice',
                    workflow_phase = 'Notice'
                WHERE workflow_stage IN ('notice_1', 'notice_2', 'notice_3')
                """
            )
            cr.execute(
                """
                UPDATE bharat_loan
                SET workflow_stage = 'appointment_of_arbitrator',
                    workflow_phase = 'Appointment of Arbitrator'
                WHERE workflow_stage IN ('auto_award', 'preference_arbitrator', 'call_for_arbitration')
                """
            )
            cr.execute(
                """
                UPDATE bharat_loan
                SET workflow_stage = 'hearing',
                    workflow_phase = 'Hearing'
                WHERE workflow_stage = 'settled'
                """
            )
            cr.execute(
                """
                UPDATE bharat_notification_template
                SET notice_type = 'notice'
                WHERE notice_type IN ('notice_1', 'notice_2', 'notice_3')
                """
            )
            cr.execute(
                """
                UPDATE bharat_notification_template
                SET notice_type = 'hearing'
                WHERE notice_type = 'settled'
                """
            )
            repair_loan_foreign_key_columns(cr)
            repair_loan_arbitrator_id_column(cr)
            repair_loan_hearing_columns(cr)
            seed_bharatnyay_demo_users_and_roles(cr)
            cr.commit()
        except Exception:
            cr.rollback()
            _logger.exception('bharatnyay_core: bharat.loan FK column repair failed; run Odoo upgrade')
        finally:
            cr.close()


class BharatLoanNoticeLine(models.Model):
    _name = 'bharat.loan.notice.line'
    _description = 'Loan notice dispatch history'
    _order = 'sent_on desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    notice_number = fields.Integer(string='Notice #', default=1, index=True)
    notice_label = fields.Char(string='Notice label', compute='_compute_notice_label', store=True)
    notice_type = fields.Selection([('notice', 'Notice')], default='notice', required=True)
    sent_on = fields.Datetime(string='Sent on', default=fields.Datetime.now, required=True)
    sent_by_id = fields.Many2one('res.users', string='Sent by', default=lambda self: self.env.user, required=True)
    recipient_partner_id = fields.Many2one(
        'res.partner',
        string='Sent to (contact)',
        ondelete='set null',
        index=True,
    )
    sent_to = fields.Char(string='Sent to (email)', required=True)
    subject = fields.Char(string='Subject')
    body_html = fields.Html(string='Email body')
    notice_pdf = fields.Binary(string='Notice PDF', attachment=True)
    notice_pdf_filename = fields.Char(string='Notice PDF filename')
    response_pdf = fields.Binary(string='Respondent response PDF', attachment=True)
    response_pdf_filename = fields.Char(string='Response filename')
    response_notes = fields.Text(string='Response notes')
    response_received_on = fields.Datetime(string='Response received on')

    @api.depends('notice_number')
    def _compute_notice_label(self):
        for rec in self:
            rec.notice_label = 'Notice %s' % (rec.notice_number or 1)

    def action_record_response(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record respondent reply'),
            'res_model': 'bharat.loan.notice.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_notice_line_id': self.id},
        }


class BharatLoanHearingLine(models.Model):
    _name = 'bharat.loan.hearing.line'
    _description = 'Loan hearing schedule history'
    _order = 'hearing_datetime desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    hearing_datetime = fields.Datetime(string='Hearing date/time', required=True)
    link_type = fields.Selection(
        [('external', 'External conferencing'), ('odoo', 'Odoo case link')],
        default='external',
        required=True,
    )
    meeting_link = fields.Char(string='Meeting/case link')
    notes = fields.Text(string='Hearing instructions')
    invitees = fields.Char(string='Invitees')
    created_by_id = fields.Many2one('res.users', string='Created by', default=lambda self: self.env.user)


class BharatLoanInterimOrder(models.Model):
    _name = 'bharat.loan.interim.order'
    _description = 'Loan interim orders'
    _order = 'order_date desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    hearing_line_id = fields.Many2one('bharat.loan.hearing.line', string='Related hearing')
    order_date = fields.Datetime(string='Order date', default=fields.Datetime.now, required=True)
    amount = fields.Monetary(string='Interim amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    notes = fields.Text(string='Order notes')
    order_pdf = fields.Binary(string='Interim order PDF', attachment=True)
    order_pdf_filename = fields.Char(string='Interim PDF filename')
    created_by_id = fields.Many2one('res.users', string='Created by', default=lambda self: self.env.user)


class BharatLoanAwardDocument(models.Model):
    _name = 'bharat.loan.award.document'
    _description = 'Loan award documents'
    _order = 'award_date desc, id desc'

    loan_id = fields.Many2one('bharat.loan', required=True, ondelete='cascade', index=True)
    award_type = fields.Selection(
        [('interim', 'Interim award'), ('final', 'Final award')],
        default='final',
        required=True,
    )
    award_date = fields.Datetime(string='Award date', default=fields.Datetime.now, required=True)
    award_notes = fields.Text(string='Award summary')
    award_pdf = fields.Binary(string='Award PDF', attachment=True)
    award_pdf_filename = fields.Char(string='Award filename')
    created_by_id = fields.Many2one('res.users', string='Created by', default=lambda self: self.env.user)
