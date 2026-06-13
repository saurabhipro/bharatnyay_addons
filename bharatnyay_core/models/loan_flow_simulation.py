# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanFlowSimulation(models.TransientModel):
    _name = 'bharat.loan.flow.simulation'
    _description = 'Guided end-to-end case flow demo'

    loan_id = fields.Many2one('bharat.loan', string='Demo case', readonly=True)
    step_index = fields.Integer(default=0, readonly=True)
    log_text = fields.Text(string='Simulation log', readonly=True)
    filter_region_id = fields.Many2one('bharat.region', readonly=True)
    filter_state_id = fields.Many2one('res.country.state', readonly=True)
    filter_batch_number = fields.Char(readonly=True)
    invoice_id = fields.Many2one('account.move', string='Generated invoice', readonly=True)

    @api.model
    def _flow_steps(self):
        return (
            {
                'key': 'open_case',
                'title': _('Open the case'),
                'subtitle': _('Starting at Commencement — watch the case file come alive.'),
                'icon': 'fa-folder-open-o',
                'mode': 'interactive',
                'action': 'open_case',
                'prompt': _('Review the case file, then continue the guided demo.'),
            },
            {
                'key': 'notice_1',
                'title': _('Notice 1'),
                'subtitle': _('Case manager assigned · notice row created.'),
                'icon': 'fa-envelope-o',
                'mode': 'auto',
                'handler': '_step_advance_once',
                'pause': 1600,
            },
            {
                'key': 'pod_n1',
                'title': _('POD — Notice 1 delivered'),
                'subtitle': _('Postal delivery confirmed · unbilled charge queued.'),
                'icon': 'fa-truck',
                'mode': 'auto',
                'handler': '_step_mark_pod',
                'doc_type': 'notice_1',
                'pause': 1400,
            },
            {
                'key': 'hearing_1',
                'title': _('Advance to Hearing 1'),
                'subtitle': _('Notice 2 & 3 cleared · arbitrator appointed.'),
                'icon': 'fa-video-camera',
                'mode': 'auto',
                'handler': '_step_advance_until',
                'target_code': 'hearing_1',
                'pause': 1800,
            },
            {
                'key': 'schedule_hearing',
                'title': _('Schedule hearing'),
                'subtitle': _('Pick a slot — the video hearing invite is sent.'),
                'icon': 'fa-calendar-check-o',
                'mode': 'interactive',
                'action': 'schedule_hearing',
                'prompt': _('Complete the hearing scheduler, then continue.'),
            },
            {
                'key': 'interim_order',
                'title': _('Pass interim order'),
                'subtitle': _('Draft, preview PDF, and record an interim award.'),
                'icon': 'fa-gavel',
                'mode': 'interactive',
                'action': 'pass_interim_award',
                'prompt': _('Record the interim order (or cancel the wizard to skip), then continue.'),
            },
            {
                'key': 'award',
                'title': _('Advance to Award'),
                'subtitle': _('Remaining hearings cleared · award document prepared.'),
                'icon': 'fa-trophy',
                'mode': 'auto',
                'handler': '_step_advance_until',
                'target_code': 'award',
                'pause': 1800,
            },
            {
                'key': 'pod_all',
                'title': _('POD billing rows'),
                'subtitle': _('Confirm postal delivery for billable documents.'),
                'icon': 'fa-check-circle',
                'mode': 'auto',
                'handler': '_step_mark_all_pod',
                'pause': 1400,
            },
            {
                'key': 'final_award',
                'title': _('Pass final award'),
                'subtitle': _('Sign-off the award letter on the case.'),
                'icon': 'fa-legal',
                'mode': 'interactive',
                'action': 'pass_final_award',
                'prompt': _('Record the final award, then continue to billing.'),
            },
            {
                'key': 'invoice',
                'title': _('Consolidated invoice'),
                'subtitle': _('Bill all pending charges for this lender / batch.'),
                'icon': 'fa-file-text-o',
                'mode': 'auto',
                'handler': '_step_create_invoice',
                'pause': 1200,
            },
            {
                'key': 'complete',
                'title': _('Flow complete'),
                'subtitle': _('Commencement → Award → Invoice — demo finished.'),
                'icon': 'fa-flag-checkered',
                'mode': 'auto',
                'handler': '_step_complete',
                'pause': 0,
            },
        )

    MILESTONE_ORDER = (
        'commencement', 'notice_1', 'notice_2', 'notice_3',
        'hearing_1', 'hearing_2', 'hearing_3', 'award',
    )
    STEP_START_CODE = {
        'open_case': 'commencement',
        'notice_1': 'commencement',
        'pod_n1': 'notice_1',
        'hearing_1': 'notice_3',
        'schedule_hearing': 'hearing_1',
        'interim_order': 'hearing_1',
        'award': 'hearing_3',
        'pod_all': 'award',
        'final_award': 'award',
        'invoice': 'award',
        'complete': 'award',
    }

    @api.model
    def _ensure_action_views(self, action):
        """Odoo 18 web client requires act_window.actions to include views."""
        if not isinstance(action, dict):
            return action
        if action.get('type') != 'ir.actions.act_window':
            return action
        if action.get('views'):
            return action
        view_mode = action.get('view_mode') or 'form'
        patched = dict(action)
        patched['views'] = [
            (False, mode.strip())
            for mode in view_mode.split(',')
            if mode.strip()
        ] or [(False, 'form')]
        return patched

    @api.model
    def _milestone_rank(self, code):
        try:
            return self.MILESTONE_ORDER.index(code or 'commencement')
        except ValueError:
            return 0

    @api.model
    def _initial_step_index(self, loan):
        loan_rank = self._milestone_rank(loan._milestone_code())
        for index, step in enumerate(self._flow_steps()):
            start_code = self.STEP_START_CODE.get(step['key'], 'commencement')
            if loan_rank <= self._milestone_rank(start_code):
                return index
        return max(len(self._flow_steps()) - 1, 0)

    @api.model
    def _dashboard_filter_domain(self, region_id=False, state_id=False, batch_number=False):
        return self.env['bharat.loan']._dashboard_apply_scope_filters(
            [], region_id=region_id, state_id=state_id, batch_number=batch_number,
        )

    @api.model
    def _pick_simulation_loan(self, region_id=False, state_id=False, batch_number=False):
        Loan = self.env['bharat.loan'].sudo()
        domain = self._dashboard_filter_domain(region_id, state_id, batch_number)
        award_ms = self.env['bharat.loan.milestone'].sudo().search(
            [('code', '=', 'award')], limit=1,
        )
        award_seq = award_ms.sequence if award_ms else 999

        for code in ('commencement', 'notice_1', 'notice_2', 'notice_3', 'hearing_1'):
            loan = Loan.search(
                domain + [('milestone_code', '=', code)],
                order='id',
                limit=1,
            )
            if loan:
                return loan

        return Loan.search(
            domain + [
                ('is_case_locked', '=', False),
                ('milestone_id.sequence', '<=', award_seq),
            ],
            order='milestone_id, id',
            limit=1,
        )

    @api.model
    def dashboard_simulation_available(self, region_id=False, state_id=False, batch_number=False):
        return bool(self._pick_simulation_loan(region_id, state_id, batch_number))

    @api.model
    def start_simulation(self, region_id=False, state_id=False, batch_number=False):
        loan = self._pick_simulation_loan(region_id, state_id, batch_number)
        if not loan:
            raise UserError(
                _('No suitable demo case in the current filter. Import a batch or widen filters.')
            )
        sim = self.create({
            'loan_id': loan.id,
            'step_index': self._initial_step_index(loan),
            'filter_region_id': region_id or False,
            'filter_state_id': state_id or False,
            'filter_batch_number': batch_number or False,
            'log_text': _('Demo case: %s (%s)\n') % (
                loan.case_number or loan.loan_number or loan.id,
                loan.milestone_id.name or loan.milestone_code or '?',
            ),
        })
        return sim._payload()

    def _advance_context(self):
        return {
            'bharat_defer_milestone_pdf': True,
            'bharat_skip_milestone_email': True,
            'bharat_skip_milestone_sms': True,
        }

    def _append_log(self, step, message):
        self.ensure_one()
        line = '[%s] %s' % (step.get('title') or step.get('key'), message or '')
        self.log_text = (self.log_text or '') + line + '\n'

    def _payload(self, **extra):
        self.ensure_one()
        steps = self._flow_steps()
        total = len(steps)
        current = steps[self.step_index] if self.step_index < total else None
        loan = self.loan_id
        data = {
            'simulation_id': self.id,
            'loan_id': loan.id,
            'loan_label': loan.case_number or loan.loan_number or loan.display_name,
            'milestone_label': loan.milestone_id.name or loan.milestone_code or '',
            'step_index': self.step_index,
            'step_total': total,
            'done': self.step_index >= total,
            'steps': [
                {
                    'key': s['key'],
                    'title': s['title'],
                    'icon': s.get('icon', 'fa-circle-o'),
                    'state': (
                        'done' if i < self.step_index
                        else 'current' if i == self.step_index
                        else 'pending'
                    ),
                }
                for i, s in enumerate(steps)
            ],
            'current_step': current and {
                'key': current['key'],
                'title': current['title'],
                'subtitle': current.get('subtitle', ''),
                'icon': current.get('icon', 'fa-circle-o'),
                'mode': current.get('mode', 'auto'),
                'prompt': current.get('prompt', ''),
            },
            'log_text': self.log_text or '',
            'invoice_id': self.invoice_id.id if self.invoice_id else False,
        }
        data.update(extra)
        return data

    def _client_action_for_step(self, step):
        self.ensure_one()
        loan = self.loan_id
        action = step.get('action')
        if action == 'open_case':
            return self._ensure_action_views({
                'type': 'ir.actions.act_window',
                'name': loan.display_name,
                'res_model': 'bharat.loan',
                'res_id': loan.id,
                'view_mode': 'form',
                'target': 'new',
            })
        if action == 'schedule_hearing':
            loan.invalidate_recordset([
                'milestone_id', 'milestone_code', 'hearing_datetime', 'arbitrator_id',
            ])
            if loan._is_hearing_milestone():
                return self._ensure_action_views(loan.action_reschedule_hearing())
            if not loan.arbitrator_id:
                loan.with_context(**self._advance_context())._set_milestone_by_code('hearing_1')
                loan.invalidate_recordset(['arbitrator_id'])
            return self._ensure_action_views(loan.action_schedule_hearing())
        if action == 'pass_interim_award':
            return self._ensure_action_views(loan.action_pass_interim_award())
        if action == 'pass_final_award':
            return self._ensure_action_views({
                'type': 'ir.actions.act_window',
                'name': _('Pass Final Award'),
                'res_model': 'bharat.loan.interim.award.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_loan_id': loan.id,
                    'default_is_final_award': True,
                },
            })
        raise UserError(_('Unknown simulation action: %s') % action)

    def _run_step_handler(self, step):
        self.ensure_one()
        handler_name = step.get('handler')
        if not handler_name:
            return ''
        handler = getattr(self, handler_name, None)
        if not handler:
            raise UserError(_('Simulation handler missing: %s') % handler_name)
        return handler(step)

    def _step_advance_once(self, step):
        loan = self.loan_id.with_context(**self._advance_context())
        name, skip = loan._advance_one_milestone()
        if skip:
            raise UserError(skip)
        return _('Moved to %s') % name

    def _step_advance_until(self, step):
        loan = self.loan_id
        target = step.get('target_code')
        ctx = self._advance_context()
        for _i in range(12):
            loan.invalidate_recordset(['milestone_id', 'milestone_code'])
            if (loan.milestone_code or '') == target:
                return _('Now at %s') % (loan.milestone_id.name or target)
            if not loan._next_milestone_record():
                break
            name, skip = loan.with_context(**ctx)._advance_one_milestone()
            if skip:
                raise UserError(skip)
        if (loan.milestone_code or '') != target:
            raise UserError(
                _('Could not reach %(target)s — stopped at %(current)s.')
                % {
                    'target': target,
                    'current': loan.milestone_id.name or loan.milestone_code,
                }
            )
        return _('Advanced to %s') % (loan.milestone_id.name or target)

    def _step_mark_pod(self, step):
        return self._mark_pod_doc_type(step.get('doc_type'))

    def _step_mark_all_pod(self, step):
        messages = []
        for doc_type in ('notice_1', 'interim_order_1', 'award'):
            msg = self._mark_pod_doc_type(doc_type, silent_if_done=True)
            if msg:
                messages.append(msg)
        return '; '.join(messages) if messages else _('All POD rows already confirmed.')

    def _mark_pod_doc_type(self, doc_type, silent_if_done=False):
        if not doc_type:
            return ''
        Dispatch = self.env['bharat.loan.postal.dispatch'].sudo()
        delivered = self.env.ref(
            'bharatnyay_core.post_office_status_delivered',
            raise_if_not_found=False,
        )
        if not delivered:
            delivered = self.env['bharat.post.office.status'].search(
                [('code', '=', 'delivered')], limit=1,
            )
        if not delivered:
            raise UserError(_('Delivered post office status is not configured.'))
        dispatch = Dispatch.ensure_for_loan(self.loan_id, doc_type)
        if dispatch._dispatch_pod_done():
            return '' if silent_if_done else _('%s POD already confirmed.') % dispatch.document_label
        today = fields.Date.context_today(self)
        vals = {
            'post_office_status_id': delivered.id,
            'delivery_date': dispatch.delivery_date or today,
        }
        if not dispatch.dispatch_date and not (dispatch.pod or '').strip():
            vals['dispatch_date'] = today
            vals['pod'] = 'SIM-%s' % (doc_type or 'POD')
        dispatch.write(vals)
        label = dispatch.document_label or doc_type
        if dispatch.billing_accrued:
            return _('%s delivered · charge accrued') % label
        return _('%s delivery confirmed') % label

    def _step_create_invoice(self, step):
        Event = self.env['bharat.loan.billing.event'].sudo()
        Move = self.env['account.move'].sudo()
        loan = self.loan_id
        events = Event.search([
            ('loan_id', '=', loan.id),
            ('state', '=', 'pending'),
        ])
        if not events:
            events = Event.search([
                ('state', '=', 'pending'),
                ('company_id', '=', loan.company_id.id),
            ])
        if not events:
            return _('No pending unbilled charges to invoice.')
        batch_name = (loan.batch_number or '').strip() or None
        moves = Move.browse()
        for company in events.mapped('company_id'):
            company_events = events.filtered(lambda e: e.company_id == company)
            moves |= Move.bharat_create_consolidated_from_events(
                company_events,
                batch_names=[batch_name] if batch_name else None,
                milestone_codes=None,
            )
        self.invoice_id = moves[:1].id if moves else False
        if len(moves) == 1:
            return _('Invoice %s posted.') % (moves.name or moves.display_name)
        return _('Created %s consolidated invoice(s).') % len(moves)

    def _step_complete(self, step):
        return _('End-to-end demo complete.')

    def advance_simulation(self, confirmed=False):
        self.ensure_one()
        steps = self._flow_steps()
        if self.step_index >= len(steps):
            return self._payload(done=True)

        step = steps[self.step_index]
        if step.get('mode') == 'interactive' and not confirmed:
            return self._payload(
                wait=True,
                client_action=self._ensure_action_views(
                    self._client_action_for_step(step),
                ),
                message=step.get('prompt') or step.get('subtitle'),
            )

        if step.get('mode') == 'interactive' and confirmed:
            message = _('Step completed.')
        else:
            message = self._run_step_handler(step)
        self._append_log(step, message)
        self.step_index += 1
        done = self.step_index >= len(steps)
        next_step = steps[self.step_index] if not done else None
        payload = self._payload(
            message=message,
            auto_continue=bool(next_step and next_step.get('mode') == 'auto'),
            auto_pause_ms=step.get('pause', 1400) if not done else 0,
            done=done,
        )
        if done and self.invoice_id:
            payload['invoice_action'] = self._ensure_action_views({
                'type': 'ir.actions.act_window',
                'name': self.invoice_id.display_name,
                'res_model': 'account.move',
                'res_id': self.invoice_id.id,
                'view_mode': 'form',
                'target': 'new',
            })
        return payload

    def open_case_action(self):
        self.ensure_one()
        return self._ensure_action_views(
            self._client_action_for_step({'action': 'open_case'}),
        )
