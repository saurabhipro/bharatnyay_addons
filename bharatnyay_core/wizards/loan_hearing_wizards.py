# -*- coding: utf-8 -*-
import json
from datetime import datetime, time as dt_time, timedelta

import pytz
from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_datetime


class BharatLoanHearingSlotLine(models.TransientModel):
    _name = 'bharat.loan.hearing.slot.line'
    _description = '30-minute hearing slot option'
    _order = 'slot_start'

    wizard_id = fields.Many2one(
        'bharat.loan.hearing.schedule.wizard',
        required=True,
        ondelete='cascade',
    )
    slot_start = fields.Datetime(required=True)

    def name_get(self):
        res = []
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        for rec in self:
            label = format_datetime(
                self.env,
                rec.slot_start,
                tz=tz_name,
                dt_format='medium',
            )
            res.append((rec.id, label))
        return res


class BharatLoanHearingScheduleWizard(models.TransientModel):
    _name = 'bharat.loan.hearing.schedule.wizard'
    _description = 'Schedule arbitration hearing'

    @staticmethod
    def _as_naive_datetime(value):
        if not value:
            return None
        if isinstance(value, str):
            return fields.Datetime.from_string(value)
        return value

    SLOT_MINUTES = 30
    # Business hours: 16 × 30 min slots = 09:00–17:00 local (last block 16:30–17:00).
    DAY_START_HOUR = 9
    GRID_SLOT_COUNT = 16

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    hearing_reschedule = fields.Boolean(
        string='Reschedule mode',
        default=False,
        help='Technical: opened from Hearing stage to move date/time without leaving the stage.',
    )
    scheduler_date = fields.Date(
        string='Pick a day',
        help='Shows 30-minute slots for the arbitrator that are still free on this day.',
    )
    use_manual_time = fields.Boolean(
        string='Enter time manually',
        help='Skip suggested slots and type any date & time below.',
    )
    slot_line_ids = fields.One2many(
        'bharat.loan.hearing.slot.line',
        'wizard_id',
        string='Available slots',
    )
    selected_slot_id = fields.Many2one(
        'bharat.loan.hearing.slot.line',
        string='Choose slot',
        help='Legacy helper row (hidden); scheduling uses the grid selection.',
    )
    slot_board_json = fields.Char(
        string='Slot board payload',
        default='{}',
        help='JSON consumed by the scheduling grid widget.',
    )
    grid_selected_index = fields.Integer(
        string='Selected grid slot',
        default=0,
        help='1–16 half-hour blocks (09:00–17:00 local).',
    )
    selected_slot_range_display = fields.Char(
        string='Selected time',
        default='',
        help='Lean label like 09:30–10:00 after you pick a grid slot.',
    )

    hearing_datetime = fields.Datetime(
        string='Hearing date & time',
        required=True,
        help='When the hearing will begin (shown in invitations).',
    )
    invite_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='bharat_ln_hearwiz_inv_users_rel',
        column1='wizard_id',
        column2='user_id',
        string='Internal attendees',
        help='Odoo users added to the calendar meeting (arbitrator is added automatically).',
    )
    external_attendee_partner_ids = fields.Many2many(
        comodel_name='res.partner',
        relation='bharat_ln_hearwiz_ext_attendee_rel',
        column1='wizard_id',
        column2='partner_id',
        string='External attendees (contacts)',
        help='Existing contacts who are not Odoo users. Each needs a valid email.',
    )
    external_attendee_emails = fields.Text(
        string='External attendee emails',
        help='Paste one or more emails (comma, semicolon, or line-separated). '
        'A contact is created automatically when needed.',
    )
    is_final_award = fields.Boolean(string='Is final award', default=False)
    was_user_present = fields.Boolean(string='Was user present', default=False)

    # Grid uses slot_board_json only. Never persist slot_line_ids: without a nested list view
    # the web client POSTs empty rows and violates slot_start NOT NULL on save.

    @api.model_create_multi
    def create(self, vals_list):
        cleaned = []
        for vals in vals_list:
            v = dict(vals)
            v.pop('slot_line_ids', None)
            v.pop('selected_slot_id', None)
            v.pop('hearing_notes', None)
            cleaned.append(v)
        return super().create(cleaned)

    def write(self, vals):
        vals = dict(vals)
        vals.pop('slot_line_ids', None)
        vals.pop('selected_slot_id', None)
        vals.pop('hearing_notes', None)
        return super().write(vals)

    def _slot_range_label_from_index(self, scheduler_date, index):
        """Return 'HH:MM–HH:MM' in the user's TZ for the chosen grid cell."""
        self.ensure_one()
        if not scheduler_date or not index:
            return ''
        tz = self._user_timezone()
        starts = self._fixed_grid_local_starts(scheduler_date, tz)
        if not (1 <= index <= len(starts)):
            return ''
        a = starts[index - 1]
        b = a + timedelta(minutes=self.SLOT_MINUTES)
        return '%s–%s' % (a.strftime('%H:%M'), b.strftime('%H:%M'))

    # ── Slot helpers ────────────────────────────────────────────────────

    @api.model
    def _user_timezone(self):
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        return pytz.timezone(tz_name)

    @api.model
    def _default_scheduler_date_for_loan(self, loan):
        tz = self._user_timezone()
        now_local = datetime.now(tz)
        return now_local.date() + timedelta(days=1)

    @api.model
    def _busy_hearing_starts_utc(self, arbitrator_user, exclude_loan):
        """Naive UTC datetimes marking occupied 30-minute blocks (block starts at each returned time)."""
        Loan = self.env['bharat.loan']
        Line = self.env['bharat.loan.hearing.line']
        busy = []

        line_domain = [('loan_id.arbitrator_id', '=', arbitrator_user.id)]
        if exclude_loan:
            line_domain.append(('loan_id', '!=', exclude_loan.id))
        for line in Line.search(line_domain):
            dt = self._as_naive_datetime(line.hearing_datetime)
            if dt:
                busy.append(dt)

        loan_domain = [
            ('arbitrator_id', '=', arbitrator_user.id),
            ('milestone_code', 'in', ['hearing_1', 'hearing_2', 'hearing_3']),
            ('hearing_datetime', '!=', False),
        ]
        if exclude_loan:
            loan_domain.append(('id', '!=', exclude_loan.id))
        for row in Loan.search(loan_domain):
            dt = self._as_naive_datetime(row.hearing_datetime)
            if dt:
                busy.append(dt)

        # De-dupe identical starts (minute precision)
        seen = set()
        out = []
        for dt in busy:
            key = fields.Datetime.to_string(dt.replace(second=0, microsecond=0))
            if key not in seen:
                seen.add(key)
                out.append(dt)
        return out

    @api.model
    def _slot_interval_overlaps(self, slot_start_utc_naive, busy_starts_utc_naive, slot_minutes=SLOT_MINUTES):
        slot_end = slot_start_utc_naive + timedelta(minutes=slot_minutes)
        for b in busy_starts_utc_naive:
            bend = b + timedelta(minutes=slot_minutes)
            if slot_start_utc_naive < bend and slot_end > b:
                return True
        return False

    @api.model
    def _fixed_grid_local_starts(self, day_date, tz):
        """Exactly GRID_SLOT_COUNT local starts from DAY_START_HOUR in 30-minute steps."""
        out = []
        t = tz.localize(datetime.combine(day_date, dt_time(self.DAY_START_HOUR, 0)))
        step = timedelta(minutes=self.SLOT_MINUTES)
        for _ in range(self.GRID_SLOT_COUNT):
            out.append(t)
            t += step
        return out

    @api.model
    def _grid_index_for_datetime_on_day(self, scheduler_day, utc_naive_dt):
        """Return 1-based grid index if utc_naive_dt falls on one of the day's slots, else 0."""
        if not scheduler_day or not utc_naive_dt:
            return 0
        tz = self._user_timezone()
        target = fields.Datetime.to_string(utc_naive_dt.replace(second=0, microsecond=0))
        for idx, loc in enumerate(self._fixed_grid_local_starts(scheduler_day, tz), start=1):
            u = loc.astimezone(pytz.UTC).replace(tzinfo=None)
            if fields.Datetime.to_string(u) == target:
                return idx
        return 0

    def _arbitrator_for_slot_board(self):
        self.ensure_one()
        arb_id = self.env.context.get('slot_board_arbitrator_id')
        if arb_id:
            return self.env['res.users'].browse(arb_id)
        return self.loan_id.arbitrator_id if self.loan_id else self.env['res.users']

    @api.model
    def public_slot_board_payload(self, loan_id, arbitrator_id, scheduler_date):
        """Slot grid for public notice microsite (arbitrator may not be on loan yet)."""
        loan = self.env['bharat.loan'].sudo().browse(loan_id)
        if not loan.exists() or not arbitrator_id or not scheduler_date:
            return {'slots': []}
        if isinstance(scheduler_date, str):
            scheduler_date = fields.Date.from_string(scheduler_date)
        wiz = self.with_context(slot_board_arbitrator_id=int(arbitrator_id)).new({
            'loan_id': loan.id,
            'scheduler_date': scheduler_date,
        })
        return wiz._slot_board_dict()

    @api.model
    def public_slot_entry(self, loan_id, arbitrator_id, scheduler_date, grid_index):
        """Return the slot dict if index is a free slot, else None."""
        try:
            grid_index = int(grid_index)
        except (TypeError, ValueError):
            return None
        if not grid_index:
            return None
        board = self.public_slot_board_payload(loan_id, arbitrator_id, scheduler_date)
        for slot in board.get('slots', []):
            if slot.get('index') == grid_index and slot.get('status') == 'free':
                return slot
        return None

    def _slot_board_dict(self):
        self.ensure_one()
        au = self._arbitrator_for_slot_board()
        if not self.scheduler_date or not au:
            return {'slots': []}
        Block = self.env['bharat.arbitrator.blockout'].sudo()
        day = self.scheduler_date
        if Block.search(
            [
                ('user_id', '=', au.id),
                ('date_start', '<=', day),
                ('date_end', '>=', day),
            ],
            limit=1,
        ):
            tz = self._user_timezone()
            slots = []
            for idx, local_start in enumerate(self._fixed_grid_local_starts(self.scheduler_date, tz), start=1):
                utc_naive = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
                utc_str = fields.Datetime.to_string(utc_naive)
                label = local_start.strftime('%H:%M')
                slots.append({
                    'index': idx,
                    'label': label,
                    'status': 'unavailable',
                    'available': False,
                    'utc': utc_str,
                })
            return {'slots': slots}
        busy = self._busy_hearing_starts_utc(au, exclude_loan=self.loan_id)
        tz = self._user_timezone()
        slots = []
        now_local = datetime.now(tz)
        for idx, local_start in enumerate(self._fixed_grid_local_starts(self.scheduler_date, tz), start=1):
            utc_naive = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
            utc_str = fields.Datetime.to_string(utc_naive)
            label = local_start.strftime('%H:%M')
            booked = self._slot_interval_overlaps(utc_naive, busy)
            unavailable_time = local_start < now_local
            if booked:
                status = 'booked'
            elif unavailable_time:
                status = 'unavailable'
            else:
                status = 'free'
            slots.append({
                'index': idx,
                'label': label,
                'status': status,
                'available': status == 'free',
                'utc': utc_str,
            })
        return {'slots': slots}

    def _sync_slot_board_json(self):
        for wiz in self:
            wiz.slot_board_json = json.dumps(wiz._slot_board_dict())

    def _utc_naive_for_grid_index(self, scheduler_date, index):
        self.ensure_one()
        if not scheduler_date or not index:
            return None
        tz = self._user_timezone()
        starts = self._fixed_grid_local_starts(scheduler_date, tz)
        if not (1 <= index <= len(starts)):
            return None
        local_start = starts[index - 1]
        return local_start.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.onchange('scheduler_date', 'loan_id', 'use_manual_time')
    def _onchange_refresh_slots(self):
        self.selected_slot_id = False
        self.grid_selected_index = 0
        self.selected_slot_range_display = ''
        if self.use_manual_time:
            self.slot_board_json = '{}'
            return
        if not self.loan_id or not self.scheduler_date or not self.loan_id.arbitrator_id:
            self.slot_board_json = '{}'
            return
        self._sync_slot_board_json()

    @api.onchange('grid_selected_index', 'scheduler_date', 'slot_board_json')
    def _onchange_grid_selected_index(self):
        self.ensure_one()
        if self.use_manual_time or not self.grid_selected_index or not self.scheduler_date:
            return
        try:
            payload = json.loads(self.slot_board_json or '{}')
        except json.JSONDecodeError:
            return
        for slot in payload.get('slots', []):
            if slot.get('index') == self.grid_selected_index:
                if slot.get('status') != 'free':
                    self.grid_selected_index = 0
                    st = slot.get('status')
                    if st == 'booked':
                        msg = _('That slot is already booked for this arbitrator.')
                    else:
                        msg = _('That slot is unavailable (for example it is in the past).')
                    return {'warning': {'title': _('Cannot select this slot'), 'message': msg}}
                self.hearing_datetime = slot.get('utc')
                self.selected_slot_range_display = self._slot_range_label_from_index(
                    self.scheduler_date, self.grid_selected_index
                )
                break

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        reschedule = bool(self.env.context.get('default_hearing_reschedule'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            vals['hearing_reschedule'] = reschedule
            if loan.arbitrator_id:
                vals.setdefault(
                    'invite_user_ids',
                    [(6, 0, loan.arbitrator_id.ids)],
                )
            external = loan.hearing_external_attendee_ids
            if (loan.borrower_email or '').strip():
                borrower_partner = loan._hearing_ensure_partner_for_email(
                    loan.borrower_email,
                    name=loan.customer_name or loan.borrower_email,
                )
                if borrower_partner:
                    external |= borrower_partner
            if external:
                vals.setdefault(
                    'external_attendee_partner_ids',
                    [(6, 0, external.ids)],
                )
            if reschedule and loan.hearing_datetime:
                vals.setdefault('hearing_datetime', loan.hearing_datetime)
                uz = self._user_timezone()
                hd = self._as_naive_datetime(loan.hearing_datetime)
                if hd:
                    utcaware = pytz.UTC.localize(hd.replace(tzinfo=None))
                    vals.setdefault(
                        'scheduler_date',
                        fields.Date.to_string(utcaware.astimezone(uz).date()),
                    )
            elif 'scheduler_date' in fields_list:
                vals.setdefault(
                    'scheduler_date',
                    fields.Date.to_string(self._default_scheduler_date_for_loan(loan)),
                )
            if (
                not reschedule
                and 'hearing_datetime' in fields_list
                and not vals.get('hearing_datetime')
            ):
                vals['hearing_datetime'] = fields.Datetime.to_string(
                    fields.Datetime.now() + timedelta(days=1)
                )

        if (
            loan
            and loan.arbitrator_id
            and vals.get('scheduler_date')
            and not vals.get('use_manual_time')
        ):
            day = fields.Date.from_string(vals['scheduler_date'])
            wiz_stub = self.new({
                'loan_id': loan.id,
                'scheduler_date': vals['scheduler_date'],
            })
            vals['slot_board_json'] = json.dumps(wiz_stub._slot_board_dict())
            if reschedule and vals.get('hearing_datetime'):
                hd = self._as_naive_datetime(vals['hearing_datetime'])
                gidx = self._grid_index_for_datetime_on_day(day, hd)
                if gidx:
                    vals['grid_selected_index'] = gidx
            if vals.get('grid_selected_index'):
                vals['selected_slot_range_display'] = wiz_stub._slot_range_label_from_index(
                    day, vals['grid_selected_index']
                )

        return vals

    def action_schedule(self):
        self.ensure_one()
        loan = self.loan_id
        if self.hearing_reschedule:
            if not loan._is_hearing_milestone():
                raise UserError(
                    _('Reschedule is only available when the case is already in a hearing milestone.')
                )
        elif not loan.arbitrator_id:
            raise UserError(
                _('Schedule Hearing requires an arbitrator. Assign one first or move to Hearing 1.')
            )

        if not self.use_manual_time:
            if not self.grid_selected_index:
                raise UserError(
                    _('Tap a free slot on the grid, or enable “Enter time manually”.')
                )
            utc_naive = self._utc_naive_for_grid_index(self.scheduler_date, self.grid_selected_index)
            if not utc_naive:
                raise UserError(_('Could not resolve the selected slot.'))
            tz = self._user_timezone()
            local_start = pytz.UTC.localize(utc_naive.replace(tzinfo=None)).astimezone(tz)
            if local_start < datetime.now(tz):
                raise UserError(_('Choose a future time slot.'))
            busy = self._busy_hearing_starts_utc(loan.arbitrator_id, exclude_loan=loan)
            if self._slot_interval_overlaps(utc_naive, busy):
                raise UserError(_('That slot is already booked; pick another.'))
            self.hearing_datetime = fields.Datetime.to_string(utc_naive)
        if not self.hearing_datetime:
            raise UserError(_('Set a hearing date and time.'))

        external_partners = self.external_attendee_partner_ids
        if (self.external_attendee_emails or '').strip():
            external_partners |= loan._hearing_partners_from_emails(
                self.external_attendee_emails,
            )
        calendar_event = loan._hearing_upsert_calendar_event(
            self.hearing_datetime,
            self.invite_user_ids,
            external_partners,
        )

        vals_loan = {
            'hearing_datetime': self.hearing_datetime,
            'hearing_invite_user_ids': [(6, 0, self.invite_user_ids.ids)],
            'hearing_external_attendee_ids': [(6, 0, external_partners.ids)],
            'calendar_event_id': calendar_event.id,
        }
        if not self.hearing_reschedule:
            if self.is_final_award:
                milestone = loan._milestone_by_code('award')
            else:
                hearing_no = min(max(len(loan.hearing_line_ids) + 1, 1), 3)
                milestone = loan._milestone_by_code('hearing_%d' % hearing_no)
            if milestone:
                vals_loan['milestone_id'] = milestone.id
                vals_loan['workflow_section'] = milestone.section or 1
                vals_loan['workflow_phase'] = milestone.phase or milestone.name

        loan.write(vals_loan)

        local = fields.Datetime.context_timestamp(loan, loan.hearing_datetime)
        dt_human = escape(str(local))

        meeting_url = escape((calendar_event.videocall_location or '').strip() or _('(not set)'))
        if self.is_final_award and not self.hearing_reschedule:
            header = _('<p><b>Final award — hearing logged</b></p>')
        elif self.hearing_reschedule:
            header = _('<p><b>Hearing rescheduled</b></p>')
        else:
            header = _('<p><b>Hearing scheduled</b></p>')
        chunks = [header + _('<p>When (your timezone): %s</p>') % dt_human]
        chunks.append(_('<p>Odoo meeting: %s</p>') % meeting_url)
        if self.invite_user_ids:
            chunks.append(
                '<p><b>%s</b> %s</p>'
                % (
                    escape(_('Internal attendees:')),
                    escape(', '.join(self.invite_user_ids.mapped('name'))),
                )
            )
        if external_partners:
            chunks.append(
                '<p><b>%s</b> %s</p>'
                % (
                    escape(_('External attendees:')),
                    escape(', '.join(external_partners.mapped('display_name'))),
                )
            )
        loan.message_post(body=''.join(chunks))

        invitee_names = list(self.invite_user_ids.mapped('name')) + list(
            external_partners.mapped('display_name')
        )
        invitees = ', '.join(invitee_names)
        loan.env['bharat.loan.hearing.line'].create({
            'loan_id': loan.id,
            'hearing_datetime': self.hearing_datetime,
            'calendar_event_id': calendar_event.id,
            'link_type': 'odoo',
            'meeting_link': calendar_event.videocall_location or '',
            'notes': '',
            'invitees': invitees,
            'status': 'conducted' if self.was_user_present else 'scheduled',
            'created_by_id': self.env.user.id,
        })

        return {'type': 'ir.actions.act_window_close'}


class BharatLoanInterimAwardWizard(models.TransientModel):
    _name = 'bharat.loan.interim.award.wizard'
    _description = 'Record interim arbitration award'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    order_type = fields.Selection(
        selection='_interim_order_type_selection',
        string='Interim order type',
        required=True,
    )
    purpose = fields.Char(string='Purpose')
    typical_loan_type = fields.Char(string='Typical loan type')
    passed_by = fields.Selection(
        selection='_interim_order_passed_by_selection',
        string='Passed by',
    )
    common_directions = fields.Text(string='Common directions')
    interim_award_amount = fields.Monetary(
        string='Interim amount (optional)',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one('res.currency')
    interim_award_notes = fields.Text(
        string='Additional directions / rationale',
        help='Optional extra notes logged on the chatter and saved on the interim order.',
    )
    is_final_award = fields.Boolean(string='Is final award', default=False)
    was_user_present = fields.Boolean(string='Was user present', default=False)

    @api.model
    def _interim_order_type_selection(self):
        from ..models.interim_order_types import INTERIM_ORDER_TYPE_SELECTION
        return INTERIM_ORDER_TYPE_SELECTION

    @api.model
    def _interim_order_passed_by_selection(self):
        from ..models.interim_order_types import INTERIM_ORDER_PASSED_BY_SELECTION
        return INTERIM_ORDER_PASSED_BY_SELECTION

    @api.onchange('order_type')
    def _onchange_order_type(self):
        from ..models.interim_order_types import interim_order_meta
        for wizard in self:
            if not wizard.order_type:
                continue
            meta = interim_order_meta(wizard.order_type)
            wizard.purpose = meta.get('purpose')
            wizard.typical_loan_type = meta.get('typical_loan_type')
            wizard.passed_by = meta.get('passed_by')
            wizard.common_directions = meta.get('common_directions')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            vals.setdefault('currency_id', loan.currency_id.id if loan.currency_id else False)
        return vals

    def action_confirm(self):
        self.ensure_one()
        loan = self.loan_id
        if not loan._is_hearing_milestone():
            raise UserError(_('Pass Interim Award is only available during hearing milestones.'))
        if not self.order_type:
            raise UserError(_('Select an interim order type.'))

        notes = (self.interim_award_notes or '').strip()
        summary_bits = [self.purpose, self.common_directions, notes]
        summary = '\n\n'.join(bit for bit in summary_bits if bit)

        milestone_code = 'award' if self.is_final_award else loan._milestone_code()
        milestone = loan._milestone_by_code(milestone_code)
        if not milestone:
            raise UserError(
                _('Workflow milestone “%s” is not configured.') % milestone_code
            )
        loan_vals = {
            'interim_award_date': fields.Datetime.now(),
            'interim_award_notes': summary or self.common_directions or self.purpose,
            'interim_award_amount': self.interim_award_amount or 0.0,
            'milestone_id': milestone.id,
            'workflow_section': milestone.section or 1,
            'workflow_phase': milestone.phase or milestone.name,
        }
        loan.write(loan_vals)

        amt = loan.interim_award_amount or 0.0
        sym = loan.currency_id.symbol or '' if loan.currency_id else ''
        type_label = dict(self._interim_order_type_selection()).get(self.order_type, self.order_type)

        header = _('<p><b>Final award recorded</b></p>') if self.is_final_award else _(
            '<p><b>Interim order recorded</b></p>'
        )
        chunks = [
            header + '<p><b>Type:</b> %(type)s</p><p>%(sym)s %(amt)s</p>' % {
                'type': escape(type_label),
                'sym': escape(sym),
                'amt': amt,
            },
        ]
        if self.was_user_present:
            chunks.append('<p><b>%s</b></p>' % escape(_('Borrower/respondent was present.')))
        if self.common_directions:
            chunks.append('<p><b>Directions:</b><br/>%s</p>' % escape(self.common_directions).replace('\n', '<br/>'))
        if notes:
            chunks.append('<p><b>Notes:</b><br/>%s</p>' % escape(notes).replace('\n', '<br/>'))
        loan.message_post(body=''.join(chunks))

        latest_hearing = loan.hearing_line_ids[:1]
        loan.env['bharat.loan.interim.order'].create({
            'loan_id': loan.id,
            'hearing_line_id': latest_hearing.id if latest_hearing else False,
            'order_type': self.order_type,
            'purpose': self.purpose,
            'typical_loan_type': self.typical_loan_type,
            'passed_by': self.passed_by,
            'common_directions': self.common_directions,
            'order_date': fields.Datetime.now(),
            'amount': self.interim_award_amount or 0.0,
            'currency_id': loan.currency_id.id if loan.currency_id else self.currency_id.id,
            'notes': notes,
            'created_by_id': self.env.user.id,
        })
        if self.is_final_award:
            award_doc = loan.env['bharat.loan.award.document'].create({
                'loan_id': loan.id,
                'award_type': 'final',
                'award_date': fields.Datetime.now(),
                'award_notes': summary or type_label,
                'created_by_id': self.env.user.id,
            })
            award_doc._attach_draft_award_letter()
        else:
            loan.env['bharat.loan.award.document'].create({
                'loan_id': loan.id,
                'award_type': 'interim',
                'award_date': fields.Datetime.now(),
                'award_notes': summary or type_label,
                'created_by_id': self.env.user.id,
            })

        return {'type': 'ir.actions.act_window_close'}
