# -*- coding: utf-8 -*-

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        user = self.env.user
        if user.exists() and user.has_group('base.group_user') and not user.share:
            action = user._bharat_home_action()
            if action:
                info['home_action_id'] = action.id
        return info
