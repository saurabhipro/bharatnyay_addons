# -*- coding: utf-8 -*-
from datetime import timedelta

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatLoanHearingScheduleWizard(models.TransientModel):
    _name = 'bharat.loan.hearing.schedule.wizard'
    _description = 'Schedule arbitration hearing'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    hearing_link_type = fields.Selection(
        [
            ('external', 'External conferencing URL'),
            ('odoo', 'Odoo case link'),
        ],
        string='Link type',
        default='external',
        required=True,
        help='External: paste Teams / Zoom / Meet. Odoo: store a URL that opens this loan in Odoo '
        '(use Discuss or phone for live audio/video alongside if needed).',
    )
    hearing_datetime = fields.Datetime(
        string='Hearing date & time',
        required=True,
        help='When the hearing will begin (shown in invitations).',
    )
    hearing_video_url = fields.Char(
        string='External video URL',
        help='Teams, Zoom, Meet, … — used when Link type is External.',
    )
    hearing_notes = fields.Text(
        string='Instructions for attendees',
        help='Optional logistics (PIN, dial-in, documents). Also posted to the chatter.',
    )
    invite_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='bharat_ln_hearwiz_inv_users_rel',
        column1='wizard_id',
        column2='user_id',
        string='Also email these users',
        help='Odoo internal users whose email addresses should receive hearing invitations '
        '(in addition to borrower email and arbitrator).',
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['bharat.loan'].browse(self.env.context.get('active_id'))
        if loan:
            vals.setdefault('loan_id', loan.id)
            if loan.arbitrator_id:
                vals.setdefault(
                    'invite_user_ids',
                    [(6, 0, loan.arbitrator_id.ids)],
                )
        if 'hearing_datetime' in fields_list and not vals.get('hearing_datetime'):
            vals['hearing_datetime'] = fields.Datetime.to_string(
                fields.Datetime.now() + timedelta(days=1)
            )
        return vals

    def action_schedule(self):
        self.ensure_one()
        loan = self.loan_id
        if loan.workflow_stage != 'arbitrator_appointed':
            raise UserError(
                _('Schedule Hearing is only available when the arbitrator has been appointed.')
            )

        link_type = self.hearing_link_type or 'external'
        if link_type == 'odoo':
            vid = ((loan._hearing_build_odoo_case_url()) or '').strip() or False
            if not vid:
                raise UserError(
                    _(
                        'Could not build an Odoo case link. Set the '
                        '`web.base.url` system parameter (Settings ▸ Technical ▸ System Parameters).'
                    )
                )
        else:
            vid = ((self.hearing_video_url or '').strip() or False)

        loan.write({
            'hearing_datetime': self.hearing_datetime,
            'hearing_link_type': link_type,
            'hearing_video_url': vid,
            'hearing_notes': self.hearing_notes.strip() if self.hearing_notes else False,
            'hearing_invite_user_ids': [(6, 0, self.invite_user_ids.ids)],
            'workflow_stage': 'hearing',
            'workflow_phase': 'Hearing',
        })

        local = fields.Datetime.context_timestamp(loan, loan.hearing_datetime)
        dt_human = escape(str(local))

        link_disp = escape((loan.hearing_video_url or '').strip() or _('(not set)'))
        chunks = [_('<p><b>Hearing scheduled</b></p><p>When (your timezone): %s</p>') % dt_human]
        if link_type == 'odoo':
            chunks.append(_('<p>Odoo case link: %s</p>') % link_disp)
        else:
            chunks.append(_('<p>External meeting link: %s</p>') % link_disp)
        if self.invite_user_ids:
            chunks.append(
                '<p><b>%s</b> %s</p>'
                % (
                    escape(_('Invitation list (internal users):')),
                    escape(', '.join(self.invite_user_ids.mapped('name'))),
                )
            )
        if self.hearing_notes:
            chunks.append('<p>%s</p>' % escape(self.hearing_notes.strip()).replace('\n', '<br/>'))
        loan.message_post(body=''.join(chunks))

        invitees = ', '.join(self.invite_user_ids.mapped('name'))
        loan.env['bharat.loan.hearing.line'].create({
            'loan_id': loan.id,
            'hearing_datetime': self.hearing_datetime,
            'link_type': link_type,
            'meeting_link': loan.hearing_video_url or '',
            'notes': self.hearing_notes or '',
            'invitees': invitees,
            'created_by_id': self.env.user.id,
        })

        return {'type': 'ir.actions.act_window_close'}


class BharatLoanInterimAwardWizard(models.TransientModel):
    _name = 'bharat.loan.interim.award.wizard'
    _description = 'Record interim arbitration award'

    loan_id = fields.Many2one('bharat.loan', required=True, readonly=True)
    interim_award_amount = fields.Monetary(
        string='Interim amount (optional)',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one('res.currency')
    interim_award_notes = fields.Text(
        string='Interim directions / rationale',
        required=True,
        help='Short summary logged on the chatter and saved on the case.',
    )

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
        if loan.workflow_stage != 'hearing':
            raise UserError(_('Pass Interim Award is only available during the Hearing stage.'))
        if not (self.interim_award_notes or '').strip():
            raise UserError(_('Describe the interim directions or rationale.'))

        loan.write({
            'interim_award_date': fields.Datetime.now(),
            'interim_award_notes': self.interim_award_notes.strip(),
            'interim_award_amount': self.interim_award_amount or 0.0,
        })

        amt = loan.interim_award_amount or 0.0
        sym = loan.currency_id.symbol or '' if loan.currency_id else ''

        chunks = [_('<p><b>Interim award recorded</b></p><p>%(sym)s %(amt)s</p>') %
                  {'sym': escape(sym), 'amt': amt}]
        chunks.append('<p>%s</p>' % escape(self.interim_award_notes.strip()).replace('\n', '<br/>'))
        loan.message_post(body=''.join(chunks))

        latest_hearing = loan.hearing_line_ids[:1]
        loan.env['bharat.loan.interim.order'].create({
            'loan_id': loan.id,
            'hearing_line_id': latest_hearing.id if latest_hearing else False,
            'order_date': fields.Datetime.now(),
            'amount': self.interim_award_amount or 0.0,
            'currency_id': loan.currency_id.id if loan.currency_id else self.currency_id.id,
            'notes': self.interim_award_notes.strip(),
            'created_by_id': self.env.user.id,
        })
        loan.env['bharat.loan.award.document'].create({
            'loan_id': loan.id,
            'award_type': 'interim',
            'award_date': fields.Datetime.now(),
            'award_notes': self.interim_award_notes.strip(),
            'created_by_id': self.env.user.id,
        })

        return {'type': 'ir.actions.act_window_close'}
