# -*- coding: utf-8 -*-
import base64
import json
from datetime import datetime, time as dt_time, timedelta

import pytz
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
    scheduler_view_mode = fields.Selection(
        [
            ('week', 'Week calendar'),
            ('day', 'Day grid'),
        ],
        string='View',
        default='week',
    )
    scheduler_week_start = fields.Date(
        string='Week starting',
        help='Monday of the week shown in the calendar view.',
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
    week_board_json = fields.Char(
        string='Week calendar payload',
        default='{}',
        help='JSON for the Outlook-style week scheduler widget.',
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
    grid_selected_date = fields.Char(
        string='Selected calendar day',
        help='ISO date (YYYY-MM-DD) of the tapped grid cell; avoids JS Date field serialization.',
    )
    calendar_week_start = fields.Char(
        string='Week calendar start',
        help='ISO date of the Monday shown in the week calendar (widget-managed).',
    )
    scheduler_selection_label = fields.Char(
        string='Selected slot',
        default=lambda self: _('Choose a time on the calendar below'),
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
        string='Attendees',
        help='Email addresses invited to the video hearing (comma, semicolon, or line-separated).',
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

    def _active_scheduler_date(self):
        """Day used to resolve the selected half-hour slot."""
        self.ensure_one()
        picked = (self.grid_selected_date or '').strip()
        if picked:
            return fields.Date.from_string(picked)
        return self.scheduler_date

    def _active_week_start(self):
        """Monday of the week shown in the week calendar."""
        self.ensure_one()
        raw = (self.calendar_week_start or '').strip()
        if raw:
            return fields.Date.from_string(raw)
        if self.scheduler_week_start:
            return self.scheduler_week_start
        if self.scheduler_date:
            return self._monday_of_week(self.scheduler_date)
        return False

    # ── Slot helpers ────────────────────────────────────────────────────

    @api.model
    def _user_timezone(self):
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        return pytz.timezone(tz_name)

    @api.model
    def _monday_of_week(self, day_date):
        if isinstance(day_date, str):
            day_date = fields.Date.from_string(day_date)
        if not day_date:
            return False
        return day_date - timedelta(days=day_date.weekday())

    @api.model
    def _default_scheduler_date_for_loan(self, loan):
        tz = self._user_timezone()
        now_local = datetime.now(tz)
        return now_local.date() + timedelta(days=1)

    @api.model
    def _busy_hearing_entries_utc(self, arbitrator_user, exclude_loan):
        """Occupied 30-minute blocks with loan reference for calendar display.

        Only confirmed Odoo calendar hearings count. Auto-provisioned placeholder rows
        (+1 / +10 / +30 days on arbitrator assign, link_type external, no meeting) are
        ignored so the grid does not show many loan numbers in one slot.
        """
        Loan = self.env['bharat.loan']
        entries = []

        loan_domain = [
            ('arbitrator_id', '=', arbitrator_user.id),
            ('hearing_datetime', '!=', False),
            ('calendar_event_id', '!=', False),
        ]
        if exclude_loan:
            loan_domain.append(('id', '!=', exclude_loan.id))
        for row in Loan.search(loan_domain):
            dt = self._as_naive_datetime(row.hearing_datetime)
            if not dt:
                continue
            entries.append({
                'start': dt,
                'loan_number': (row.loan_number or row.display_name or '').strip(),
                'loan_id': row.id,
                'customer_name': (row.customer_name or '').strip(),
            })

        return entries

    @api.model
    def _busy_hearing_starts_utc(self, arbitrator_user, exclude_loan):
        """Naive UTC datetimes marking occupied 30-minute blocks (block starts at each returned time)."""
        return [entry['start'] for entry in self._busy_hearing_entries_utc(arbitrator_user, exclude_loan)]

    @api.model
    def _slot_booking_for_interval(self, slot_start_utc_naive, busy_entries, slot_minutes=SLOT_MINUTES):
        slot_end = slot_start_utc_naive + timedelta(minutes=slot_minutes)
        by_loan = {}
        for entry in busy_entries:
            b = entry['start']
            bend = b + timedelta(minutes=slot_minutes)
            if slot_start_utc_naive < bend and slot_end > b:
                loan_id = entry.get('loan_id')
                label = entry.get('loan_number') or ''
                if loan_id and label:
                    by_loan[loan_id] = label
                elif label and label not in by_loan.values():
                    by_loan[label] = label
        labels = list(by_loan.values())
        if not labels:
            return None
        loan_ids = list(by_loan.keys())
        customer_names = []
        for entry in busy_entries:
            b = entry['start']
            bend = b + timedelta(minutes=slot_minutes)
            if slot_start_utc_naive < bend and slot_end > b:
                cname = (entry.get('customer_name') or '').strip()
                if cname and cname not in customer_names:
                    customer_names.append(cname)
        return {
            'loan_number': labels[0] if len(labels) == 1 else ', '.join(labels),
            'loan_id': loan_ids[0] if len(loan_ids) == 1 else False,
            'customer_name': customer_names[0] if len(customer_names) == 1 else '',
        }

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
    def get_week_board_json_for_context(self, loan_id, week_start):
        """Rebuild week calendar JSON without a full form onchange (week navigation)."""
        if not loan_id or not week_start:
            return '{}'
        if isinstance(week_start, str):
            week_start = fields.Date.from_string(week_start)
        wiz = self.new({
            'loan_id': int(loan_id),
            'calendar_week_start': fields.Date.to_string(week_start),
            'scheduler_date': week_start,
        })
        return self._slot_board_json_dumps(wiz._week_board_dict())

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

    def _slot_board_dict_for_date(self, day_date):
        """Slot board for one calendar day without mutating this wizard row."""
        self.ensure_one()
        stub = self.new({
            'loan_id': self.loan_id.id,
            'scheduler_date': day_date,
        })
        return stub._slot_board_dict()

    def _week_board_dict(self):
        self.ensure_one()
        au = self._arbitrator_for_slot_board()
        week_start = self._active_week_start()
        if not week_start or not au:
            return {
                'days': [],
                'arbitrator_name': au.name if au else '',
                'week_start': '',
                'week_end': '',
            }
        days = []
        for offset in range(5):
            day = week_start + timedelta(days=offset)
            board = self._slot_board_dict_for_date(day)
            days.append({
                'date': fields.Date.to_string(day),
                'label': '%s %s' % (day.strftime('%a'), day.day),
                'slots': board.get('slots', []),
            })
        week_end = week_start + timedelta(days=4)
        return {
            'week_start': fields.Date.to_string(week_start),
            'week_end': fields.Date.to_string(week_end),
            'arbitrator_name': au.name,
            'days': days,
        }

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
        busy_entries = self._busy_hearing_entries_utc(au, exclude_loan=None)
        tz = self._user_timezone()
        slots = []
        now_local = datetime.now(tz)
        for idx, local_start in enumerate(self._fixed_grid_local_starts(self.scheduler_date, tz), start=1):
            utc_naive = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
            utc_str = fields.Datetime.to_string(utc_naive)
            label = local_start.strftime('%H:%M')
            end_local = local_start + timedelta(minutes=self.SLOT_MINUTES)
            time_range = '%s–%s' % (label, end_local.strftime('%H:%M'))
            booking = self._slot_booking_for_interval(utc_naive, busy_entries)
            booked = bool(booking)
            unavailable_time = local_start < now_local
            if booked and self.loan_id and booking.get('loan_id') == self.loan_id.id:
                status = 'own'
            elif booked:
                status = 'booked'
            elif unavailable_time:
                status = 'unavailable'
            else:
                status = 'free'
            slot_data = {
                'index': idx,
                'label': label,
                'time_range': time_range,
                'status': status,
                'available': status in ('free', 'own'),
                'utc': utc_str,
            }
            if booked and booking.get('loan_number'):
                slot_data['loan_number'] = booking['loan_number']
            elif status == 'own' and self.loan_id:
                slot_data['loan_number'] = (
                    self.loan_id.loan_number or self.loan_id.display_name or ''
                ).strip()
            if booked and booking.get('customer_name'):
                slot_data['customer_name'] = booking['customer_name']
            elif status == 'own' and self.loan_id:
                slot_data['customer_name'] = (self.loan_id.customer_name or '').strip()
            slots.append(slot_data)
        return {'slots': slots}

    @api.model
    def _slot_board_json_dumps(self, board_dict):
        return json.dumps(board_dict, sort_keys=True, separators=(',', ':'))

    def _sync_slot_board_json(self):
        for wiz in self:
            payload = wiz._slot_board_json_dumps(wiz._slot_board_dict())
            if wiz.slot_board_json != payload:
                wiz.slot_board_json = payload

    def _sync_week_board_json(self):
        for wiz in self:
            payload = wiz._slot_board_json_dumps(wiz._week_board_dict())
            if wiz.week_board_json != payload:
                wiz.week_board_json = payload

    def _revalidate_grid_selection(self):
        """Keep or clear grid selection after the board payload changes."""
        self.ensure_one()
        idx = self.grid_selected_index
        sched_day = self._active_scheduler_date()
        if not idx or self.use_manual_time or not sched_day:
            if not idx:
                self.selected_slot_range_display = ''
            return
        try:
            payload = json.loads(self.slot_board_json or '{}')
        except json.JSONDecodeError:
            self.grid_selected_index = 0
            self.selected_slot_range_display = ''
            return
        for slot in payload.get('slots', []):
            if slot.get('index') != idx:
                continue
            if slot.get('status') in ('free', 'own'):
                self.selected_slot_range_display = self._slot_range_label_from_index(
                    sched_day, idx
                )
                return
            break
        self.grid_selected_index = 0
        self.selected_slot_range_display = ''

    def _refresh_slot_board_if_ready(self):
        self.ensure_one()
        if self.use_manual_time or not self.loan_id or not self.loan_id.arbitrator_id:
            self.slot_board_json = '{}'
            self.week_board_json = '{}'
            return
        if self.scheduler_date:
            self._sync_slot_board_json()
        if not self.scheduler_week_start and self.scheduler_date:
            self.scheduler_week_start = self._monday_of_week(self.scheduler_date)
        if self.scheduler_week_start and not self.calendar_week_start:
            self.calendar_week_start = fields.Date.to_string(self.scheduler_week_start)
        week_start = self._active_week_start()
        if week_start:
            self._sync_week_board_json()

    @api.onchange('scheduler_view_mode')
    def _onchange_scheduler_view_mode(self):
        self._refresh_slot_board_if_ready()

    @api.onchange('scheduler_week_start')
    def _onchange_scheduler_week_start(self):
        if self.use_manual_time:
            return
        self._sync_week_board_json()

    @api.onchange('scheduler_date')
    def _onchange_scheduler_date(self):
        self.selected_slot_id = False
        self.grid_selected_date = False
        if self.scheduler_date:
            monday = self._monday_of_week(self.scheduler_date)
            self.scheduler_week_start = monday
            self.calendar_week_start = fields.Date.to_string(monday)
        prev_index = self.grid_selected_index
        self._refresh_slot_board_if_ready()
        if prev_index:
            self.grid_selected_index = prev_index
            self._revalidate_grid_selection()
        elif self.hearing_reschedule and self.hearing_datetime and self.scheduler_date:
            gidx = self._grid_index_for_datetime_on_day(
                self.scheduler_date,
                self._as_naive_datetime(self.hearing_datetime),
            )
            if gidx:
                self.grid_selected_index = gidx
                self.selected_slot_range_display = self._slot_range_label_from_index(
                    self.scheduler_date, gidx
                )
        else:
            self.grid_selected_index = 0
            self.selected_slot_range_display = ''

    @api.onchange('loan_id', 'use_manual_time')
    def _onchange_loan_or_manual_time(self):
        self.selected_slot_id = False
        if self.use_manual_time:
            self.slot_board_json = '{}'
            self.week_board_json = '{}'
            self.grid_selected_index = 0
            self.selected_slot_range_display = ''
            return
        prev_index = self.grid_selected_index
        self._refresh_slot_board_if_ready()
        if prev_index:
            self.grid_selected_index = prev_index
            self._revalidate_grid_selection()
        else:
            self.grid_selected_index = 0
            self.selected_slot_range_display = ''

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

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        reschedule = bool(self.env.context.get('default_hearing_reschedule'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            vals['hearing_reschedule'] = reschedule
            invite_users = loan._hearing_default_invite_users()
            if loan.hearing_invite_user_ids:
                invite_users |= loan.hearing_invite_user_ids
            if invite_users:
                vals.setdefault('invite_user_ids', [(6, 0, invite_users.ids)])
            external = loan._hearing_default_external_partners()
            if loan.hearing_external_attendee_ids:
                external |= loan.hearing_external_attendee_ids
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
            vals.setdefault('scheduler_view_mode', 'week')
            sched_day = vals.get('scheduler_date')
            if sched_day:
                monday = self._monday_of_week(fields.Date.from_string(sched_day))
                vals.setdefault('scheduler_week_start', fields.Date.to_string(monday))
                vals.setdefault('calendar_week_start', fields.Date.to_string(monday))
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
            vals['slot_board_json'] = self._slot_board_json_dumps(wiz_stub._slot_board_dict())
            week_stub = self.new({
                'loan_id': loan.id,
                'scheduler_date': vals['scheduler_date'],
                'calendar_week_start': vals.get('calendar_week_start')
                or fields.Date.to_string(self._monday_of_week(day)),
            })
            vals['week_board_json'] = self._slot_board_json_dumps(week_stub._week_board_dict())
            if reschedule and vals.get('hearing_datetime'):
                hd = self._as_naive_datetime(vals['hearing_datetime'])
                gidx = self._grid_index_for_datetime_on_day(day, hd)
                if gidx:
                    vals['grid_selected_index'] = gidx
                    vals['grid_selected_date'] = vals['scheduler_date']
            if vals.get('grid_selected_index'):
                vals['selected_slot_range_display'] = wiz_stub._slot_range_label_from_index(
                    day, vals['grid_selected_index']
                )
                day_label = day.strftime('%a %d %b')
                vals['scheduler_selection_label'] = '%s · %s' % (
                    day_label,
                    vals['selected_slot_range_display'],
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
                    _('Tap a free slot on the calendar, or enable “Enter time manually”.')
                )
            utc_naive = self._utc_naive_for_grid_index(
                self._active_scheduler_date(),
                self.grid_selected_index,
            )
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
        dt_human = str(local)

        meeting_url = (calendar_event.videocall_location or '').strip() or _('(not set)')
        if self.is_final_award and not self.hearing_reschedule:
            header = _('Final award — hearing logged')
        elif self.hearing_reschedule:
            header = _('Hearing rescheduled')
        else:
            header = _('Hearing scheduled')
        chunks = [
            header,
            _('When (your timezone): %s') % dt_human,
            _('Odoo meeting: %s') % meeting_url,
        ]
        if self.invite_user_ids:
            chunks.append(
                '%s %s'
                % (
                    _('Internal attendees:'),
                    ', '.join(self.invite_user_ids.mapped('name')),
                )
            )
        if external_partners:
            chunks.append(
                '%s %s'
                % (
                    _('External attendees:'),
                    ', '.join(external_partners.mapped('display_name')),
                )
            )
        loan.message_post(body='\n'.join(chunks))

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
    draft_body_html = fields.Html(
        string='Interim order draft',
        sanitize=False,
        help='Editable interim order text generated from the selected type template.',
    )
    draft_pdf = fields.Binary(string='Draft PDF preview', readonly=True)
    draft_pdf_filename = fields.Char(string='Draft PDF filename', readonly=True)
    signed_order_pdf = fields.Binary(string='Signed interim order PDF')
    signed_order_pdf_filename = fields.Char(string='Signed PDF filename')
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

    def _apply_draft_template(self):
        from ..models.interim_order_types import render_interim_order_draft_html
        for wizard in self:
            if not wizard.loan_id or not wizard.order_type:
                continue
            wizard.draft_body_html = render_interim_order_draft_html(
                wizard.order_type,
                wizard.loan_id,
                amount=wizard.interim_award_amount or 0.0,
                additional_notes=wizard.interim_award_notes or '',
                common_directions=wizard.common_directions or '',
                purpose=wizard.purpose or '',
            )

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
            wizard._apply_draft_template()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            vals.setdefault('currency_id', loan.currency_id.id if loan.currency_id else False)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for wizard, vals in zip(records, vals_list):
            if vals.get('draft_body_html') or not wizard.order_type:
                continue
            wizard._apply_draft_template()
        return records

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.browse(docids).exists()
        labels = {}
        for doc in docs:
            labels[doc.id] = (
                format_datetime(doc.env, doc.create_date, dt_format='medium')
                if doc.create_date else '—'
            )
        return {
            'doc_ids': docids,
            'doc_model': self._name,
            'docs': docs,
            'interim_order_date_labels': labels,
        }

    def _draft_report(self):
        return self.env.ref(
            'bharatnyay_core.action_report_bharat_interim_award_wizard_draft',
            raise_if_not_found=False,
        )

    def _draft_pdf_filename(self):
        self.ensure_one()
        loan = self.loan_id
        ref = (loan.loan_number or loan.case_number or loan.id) if loan else self.id
        return 'Interim_Order_Draft_%s.pdf' % ref

    def _render_draft_pdf(self):
        self.ensure_one()
        if not (self.draft_body_html or '').strip():
            raise UserError(_('The interim order draft is empty. Select a type or edit the draft.'))
        report = self._draft_report()
        if not report:
            raise UserError(_('Interim order draft report is not configured.'))
        pdf_bytes, _ctype = report._render_qweb_pdf(report, res_ids=self.ids)
        return pdf_bytes

    def action_reload_template(self):
        self.ensure_one()
        self.write({'draft_pdf': False, 'draft_pdf_filename': False})
        self._apply_draft_template()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pass Interim Award'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_preview_pdf(self):
        self.ensure_one()
        pdf_bytes = self._render_draft_pdf()
        self.write({
            'draft_pdf': base64.b64encode(pdf_bytes),
            'draft_pdf_filename': self._draft_pdf_filename(),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pass Interim Award'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, show_interim_pdf_preview=True),
        }

    def action_download_draft_pdf(self):
        self.ensure_one()
        if not self.draft_pdf:
            pdf_bytes = self._render_draft_pdf()
            self.write({
                'draft_pdf': base64.b64encode(pdf_bytes),
                'draft_pdf_filename': self._draft_pdf_filename(),
            })
        filename = self.draft_pdf_filename or self._draft_pdf_filename()
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content/?model=%s&id=%s&field=draft_pdf&filename=%s&download=true'
            ) % (self._name, self.id, filename),
            'target': 'self',
        }

    def action_confirm(self):
        self.ensure_one()
        loan = self.loan_id
        if not loan._is_hearing_milestone():
            raise UserError(_('Pass Interim Award is only available during hearing milestones.'))
        if not self.order_type:
            raise UserError(_('Select an interim order type.'))
        if not (self.draft_body_html or '').strip():
            raise UserError(_('Draft the interim order before recording it.'))

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

        header = _('Final award recorded') if self.is_final_award else _('Interim order recorded')
        chunks = [
            header,
            _('Type: %s') % type_label,
            '%s %s' % (sym, amt),
        ]
        if self.was_user_present:
            chunks.append(_('Borrower/respondent was present.'))
        if self.common_directions:
            chunks.append('%s\n%s' % (_('Directions:'), self.common_directions))
        if notes:
            chunks.append('%s\n%s' % (_('Notes:'), notes))

        latest_hearing = loan.hearing_line_ids[:1]
        interim = loan.env['bharat.loan.interim.order'].create({
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
            'draft_body_html': self.draft_body_html,
            'created_by_id': self.env.user.id,
        })

        pdf_attachment = None
        if self.signed_order_pdf:
            ref = loan.loan_number or loan.case_number or loan.id
            signed_name = (self.signed_order_pdf_filename or '').strip() or (
                'Interim_Order_Signed_%s.pdf' % ref
            )
            interim.write({
                'order_pdf': self.signed_order_pdf,
                'order_pdf_filename': signed_name,
                'signed_on': fields.Datetime.now(),
            })
            pdf_attachment = (signed_name, base64.b64decode(self.signed_order_pdf))
        else:
            interim._attach_order_pdf()
            if interim.order_pdf:
                pdf_attachment = (
                    interim.order_pdf_filename or 'Interim_Order.pdf',
                    base64.b64decode(interim.order_pdf),
                )

        post_vals = {'body': '\n'.join(chunks)}
        if pdf_attachment:
            post_vals['attachments'] = [pdf_attachment]
        loan.message_post(**post_vals)

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
