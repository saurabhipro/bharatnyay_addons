# -*- coding: utf-8 -*-

from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import is_user_internal
from odoo.http import request


class BharatHome(Home):
    def _login_redirect(self, uid, redirect=None):
        if not redirect and uid and is_user_internal(uid):
            user = request.env['res.users'].sudo().browse(uid)
            if user.exists():
                redirect = user._bharat_login_redirect_path()
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_client(self, s_action=None, **kw):
        """Send bare /odoo landing to the BharatNyay dashboard (not app deep links)."""
        req_path = (request.httprequest.path or '').rstrip('/')
        if (
            request.session.uid
            and not s_action
            and not kw.get('action')
            and req_path in ('/odoo', '/web')
        ):
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user.exists() and not user.share:
                path = user._bharat_login_redirect_path()
                if path and path.startswith('/odoo/'):
                    return request.redirect(path)
        return super().web_client(s_action=s_action, **kw)
