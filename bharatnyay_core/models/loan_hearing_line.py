# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanHearingLine(models.Model):
    _name = 'bharat.loan.hearing.line'
    _description = 'Loan hearing schedule history'
    _order = 'hearing_datetime desc, id desc'
    _rec_name = 'loan_id'

    loan_id = fields.Many2one(
        'bharat.loan',
        string='Case',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    loan_number = fields.Char(
        related='loan_id.loan_number',
        string='Loan number',
        store=True,
        readonly=True,
    )
    case_number = fields.Char(
        related='loan_id.case_number',
        string='Case number',
        store=True,
        readonly=True,
    )
    batch_number = fields.Char(
        related='loan_id.batch_number',
        string='Batch',
        store=True,
        readonly=True,
        index=True,
    )
    customer_name = fields.Char(
        related='loan_id.customer_name',
        string='Borrower',
        store=True,
        readonly=True,
    )
    milestone_code = fields.Selection(
        related='loan_id.milestone_code',
        string='Milestone',
        store=True,
        readonly=True,
    )
    arbitrator_id = fields.Many2one(
        related='loan_id.arbitrator_id',
        string='Arbitrator',
        store=True,
        readonly=True,
    )
    hearing_datetime = fields.Datetime(string='Hearing date/time', required=True)
    hearing_slot_index = fields.Integer(
        string='Slot index',
        compute='_compute_hearing_slot_display',
        store=True,
    )
    hearing_slot_label = fields.Char(
        string='Slot number',
        compute='_compute_hearing_slot_display',
        store=True,
    )
    hearing_slot_time_label = fields.Char(
        string='Slot time',
        compute='_compute_hearing_slot_display',
        store=True,
    )
    minutes_remaining = fields.Integer(
        string='Minutes until hearing',
        compute='_compute_minutes_remaining',
        help='Countdown in minutes; at 0 the case moves to the Hearing stage.',
    )
    status = fields.Selection(
        [('scheduled', 'Scheduled'), ('conducted', 'Conducted')],
        default='scheduled',
        required=True,
    )
    link_type = fields.Selection(
        [('external', 'External conferencing'), ('odoo', 'Odoo case link')],
        default='external',
        required=True,
    )
    calendar_event_id = fields.Many2one(
        'calendar.event',
        string='Odoo meeting',
        ondelete='set null',
        copy=False,
    )
    meeting_link = fields.Char(string='Meeting/case link')
    notes = fields.Text(string='Hearing instructions')
    invitees = fields.Char(string='Invitees')
    created_by_id = fields.Many2one('res.users', string='Recorded by', default=lambda self: self.env.user)

    @api.depends('hearing_datetime')
    def _compute_hearing_slot_display(self):
        Wiz = self.env['bharat.loan.hearing.schedule.wizard']
        for line in self:
            line.hearing_slot_index = 0
            line.hearing_slot_label = ''
            line.hearing_slot_time_label = ''
            if not line.hearing_datetime:
                continue
            local = fields.Datetime.context_timestamp(line, line.hearing_datetime)
            day = local.date()
            utc_naive = line.hearing_datetime.replace(second=0, microsecond=0)
            idx = Wiz._grid_index_for_datetime_on_day(day, utc_naive)
            line.hearing_slot_index = idx
            if idx:
                line.hearing_slot_label = _('Slot %s') % idx
                wiz = Wiz.new({
                    'loan_id': line.loan_id.id,
                    'scheduler_date': day,
                })
                line.hearing_slot_time_label = wiz._slot_range_label_from_index(day, idx)

    @api.depends('hearing_datetime')
    def _compute_minutes_remaining(self):
        now = fields.Datetime.now()
        for line in self:
            if not line.hearing_datetime:
                line.minutes_remaining = -1
                continue
            delta = line.hearing_datetime - now
            line.minutes_remaining = max(0, int(delta.total_seconds() // 60))

    @api.model
    def _bharat_realign_batch_hearing_slots(self):
        """Assign Slot 1, 2, 3… per batch/day for existing placeholder hearings."""
        Wiz = self.env['bharat.loan.hearing.schedule.wizard']
        lines = self.sudo().search([
            ('status', '=', 'scheduled'),
            ('hearing_datetime', '!=', False),
            ('arbitrator_id', '!=', False),
        ])
        groups = {}
        for line in lines:
            local = fields.Datetime.context_timestamp(line, line.hearing_datetime)
            key = (line.batch_number or '', line.arbitrator_id.id, local.date())
            groups.setdefault(key, []).append(line)

        Loan = self.env['bharat.loan'].sudo()
        touched_loans = Loan.browse()
        for group_lines in groups.values():
            sorted_lines = sorted(
                group_lines,
                key=lambda ln: (ln.loan_number or '', ln.id),
            )
            if not sorted_lines:
                continue
            day = fields.Datetime.context_timestamp(
                sorted_lines[0], sorted_lines[0].hearing_datetime,
            ).date()
            for slot_idx, line in enumerate(sorted_lines, start=1):
                if slot_idx > Wiz.GRID_SLOT_COUNT:
                    break
                wiz = Wiz.new({'loan_id': line.loan_id.id, 'scheduler_date': day})
                utc_naive = wiz._utc_naive_for_grid_index(day, slot_idx)
                if not utc_naive:
                    continue
                current = line.hearing_datetime
                if isinstance(current, str):
                    current = fields.Datetime.from_string(current)
                if current.replace(second=0, microsecond=0) != utc_naive.replace(second=0, microsecond=0):
                    line.with_context(skip_hearing_countdown=True).write({
                        'hearing_datetime': utc_naive,
                    })
                    touched_loans |= line.loan_id

        for loan in touched_loans:
            upcoming = loan.hearing_line_ids.filtered(
                lambda ln: ln.status == 'scheduled',
            ).sorted('hearing_datetime')
            if upcoming and loan.hearing_datetime != upcoming[0].hearing_datetime:
                loan.with_context(skip_hearing_countdown=True).write({
                    'hearing_datetime': upcoming[0].hearing_datetime,
                })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('loan_id')._check_hearing_countdown_and_promote()
        return records

    def write(self, vals):
        locked_loans = self.mapped('loan_id').filtered('is_case_locked')
        if locked_loans and not self.env.context.get('bharat_allow_locked_case_write'):
            raise UserError(
                _('Case %(cases)s is at Award stage and cannot be modified.')
                % {'cases': ', '.join(locked_loans.mapped('loan_number'))}
            )
        if 'loan_id' in vals:
            vals = dict(vals)
            vals.pop('loan_id')
        res = super().write(vals)
        if 'hearing_datetime' in vals:
            self.mapped('loan_id')._check_hearing_countdown_and_promote()
        return res

    def web_read(self, specification):
        result = super().web_read(specification)
        if not self.env.context.get('skip_hearing_countdown'):
            self.mapped('loan_id')._check_hearing_countdown_and_promote()
        return result

    def action_join_meeting(self):
        """Join the Odoo Discuss videocall for this hearing."""
        self.ensure_one()
        loan = self.loan_id
        event = self.calendar_event_id
        if not event:
            if not loan.hearing_datetime and self.hearing_datetime:
                loan.with_context(skip_hearing_countdown=True).write({
                    'hearing_datetime': self.hearing_datetime,
                })
            event = loan._hearing_ensure_calendar_event()
            if event and not self.calendar_event_id:
                self.write({
                    'calendar_event_id': event.id,
                    'link_type': 'odoo',
                    'meeting_link': event.videocall_location or '',
                })
        if not event:
            raise UserError(
                _('No Odoo meeting could be created. Schedule or reschedule first.')
            )
        if not (event.videocall_location or '').strip():
            event._set_discuss_videocall_location()
        return event.action_join_video_call()

    def action_reschedule_hearing(self):
        """Open schedule wizard for this loan while staying in Hearing stage."""
        self.ensure_one()
        loan = self.loan_id
        if not loan._is_hearing_milestone():
            raise UserError(_('Reschedule from this list only applies to cases in hearing milestones.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule hearing'),
            'res_model': 'bharat.loan.hearing.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': loan.id,
                'default_loan_id': loan.id,
                'default_hearing_reschedule': True,
            },
        }


