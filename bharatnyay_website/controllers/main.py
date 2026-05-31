import json
import logging

from odoo import _, fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class BharatWebsite(http.Controller):
    """Public marketing routes, ODR primers, and optional portfolio excerpt."""

    @http.route(['/about', '/about-bharatnyay'], type='http', auth='public', website=True)
    def about_page(self, **kw):
        return request.render('bharatnyay_website.page_about_bharatnyay')

    @http.route(['/features'], type='http', auth='public', website=True)
    def features_page(self, **kw):
        return request.render('bharatnyay_website.page_features')

    @http.route(['/how-it-works'], type='http', auth='public', website=True)
    def how_it_works_page(self, **kw):
        return request.render('bharatnyay_website.page_how_it_works')

    @http.route(['/odr/what-is'], type='http', auth='public', website=True)
    def odr_what_is_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_what_is')

    @http.route(['/odr/proceedings'], type='http', auth='public', website=True)
    def odr_proceedings_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_proceedings')

    @http.route(['/odr/model-clause'], type='http', auth='public', website=True)
    def odr_model_clause_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_model_clause')

    @http.route(['/odr/standards'], type='http', auth='public', website=True)
    def odr_standards_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_standards')

    @http.route(['/odr/procedural-rules'], type='http', auth='public', website=True)
    def odr_procedural_rules_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_procedural_rules')

    @http.route(['/odr/standards/code-of-ethics'], type='http', auth='public', website=True)
    def odr_code_of_ethics_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_code_of_ethics')

    @http.route(['/odr/standards/hearing-protocol'], type='http', auth='public', website=True)
    def odr_hearing_protocol_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_hearing_protocol')

    @http.route(['/odr/standards/neutral-appointment'], type='http', auth='public', website=True)
    def odr_neutral_appointment_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_neutral_appointment')

    @http.route(['/odr/standards/empanelment'], type='http', auth='public', website=True)
    def odr_empanelment_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_empanelment')

    @http.route(['/odr/standards/video-conferencing'], type='http', auth='public', website=True)
    def odr_video_conferencing_page(self, **kw):
        return request.render('bharatnyay_website.page_odr_video_conferencing')

    @http.route(['/bharat/cases'], type='http', auth='user', website=True)
    def cases_list(self, **post):
        Loans = request.env['bharat.loan'].sudo()
        partner = request.env.user.partner_id
        # Match portfolio rows where customer name contains the user's name (tune as needed).
        name = partner.name or ''
        domain = [('customer_name', 'ilike', name)] if name else []
        loans = Loans.search(domain, limit=500, order='loan_number asc')
        return request.render(
            'bharatnyay_website.portal_my_cases',
            {'loans': loans},
        )

    def _bn_notice_default_scheduler_date(self, loan):
        Wiz = request.env['bharat.loan.hearing.schedule.wizard'].sudo()
        return Wiz._default_scheduler_date_for_loan(loan)

    @http.route(
        ['/bn/respond/<string:token>/slots'],
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def bn_notice_respond_slots(self, token, arbitrator_id=None, scheduler_date=None, **kw):
        NoticeLine = request.env['bharat.loan.notice.line'].sudo()
        line = NoticeLine.search([('qr_access_token', '=', token)], limit=1)
        if not line:
            return request.make_response('{}', status=404)

        try:
            arb_id = int(arbitrator_id or 0)
        except (TypeError, ValueError):
            arb_id = 0

        Wiz = request.env['bharat.loan.hearing.schedule.wizard'].sudo()
        payload = Wiz.public_slot_board_payload(
            line.loan_id.id,
            arb_id,
            scheduler_date,
        )
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route(
        ['/bn/respond/<string:token>'],
        type='http',
        auth='public',
        website=True,
        methods=['GET', 'POST'],
        csrf=True,
    )
    def bn_notice_respond(self, token, **post):
        NoticeLine = request.env['bharat.loan.notice.line'].sudo()
        line = NoticeLine.search([('qr_access_token', '=', token)], limit=1)
        if not line:
            return request.not_found()

        loan = line.loan_id.sudo()
        thanks_flag = bool(request.params.get('thanks'))
        error = False
        Wiz = request.env['bharat.loan.hearing.schedule.wizard'].sudo()
        default_scheduler_date = self._bn_notice_default_scheduler_date(loan)

        arbitrators = request.env['res.users'].sudo().search([
            ('bharat_role', '=', 'arbitrator'),
            ('active', '=', True),
            ('share', '=', False),
        ])

        if request.httprequest.method == 'POST':
            otp = (post.get('otp') or '').strip()
            arb_raw = post.get('arbitrator_id')
            scheduler_date = (post.get('scheduler_date') or '').strip()
            grid_raw = post.get('grid_selected_index') or '0'
            notes = (post.get('preferred_slot_notes') or '').strip()
            consent = post.get('consent')
            try:
                arb_id = int(arb_raw or 0)
            except (TypeError, ValueError):
                arb_id = 0
            try:
                grid_index = int(grid_raw or 0)
            except (TypeError, ValueError):
                grid_index = 0

            if otp != (line.microsite_otp_code or ''):
                error = _('Invalid OTP. Use the 6-digit code from your notice correspondence.')
            elif not arb_id or arb_id not in arbitrators.ids:
                error = _('Please choose an arbitrator from the approved list.')
            elif not consent:
                error = _('Please tick consent to proceed.')
            elif not scheduler_date:
                error = _('Please choose a hearing day.')
            elif not grid_index:
                error = _('Please pick an available time slot from the grid.')
            else:
                slot = Wiz.public_slot_entry(
                    loan.id, arb_id, scheduler_date, grid_index
                )
                if not slot:
                    error = _(
                        'That time slot is no longer available. Pick another slot and try again.'
                    )
                else:
                    pref_parts = [
                        '%s %s' % (scheduler_date, slot.get('label') or ''),
                    ]
                    if notes:
                        pref_parts.append(notes)
                    pref = ' · '.join(pref_parts)
                    loan.write({'arbitrator_id': arb_id})
                    line.write({
                        'borrower_slot_preference': pref,
                        'microsite_last_submit_at': fields.Datetime.now(),
                    })
                    loan.message_post(
                        body=_(
                            'Borrower submitted arbitrator and hearing slot preference via QR microsite (notice %s): %s'
                        )
                        % (line.notice_label or '', pref),
                    )
                    return request.redirect('/bn/respond/%s?thanks=1' % token)

        return request.render(
            'bharatnyay_website.bn_notice_microsite_page',
            {
                'line': line,
                'loan': loan,
                'arbitrators': arbitrators,
                'thanks': thanks_flag,
                'error': error,
                'default_scheduler_date': default_scheduler_date,
            },
        )
