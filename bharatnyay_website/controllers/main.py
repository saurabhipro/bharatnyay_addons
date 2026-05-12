import logging

from odoo import http
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
