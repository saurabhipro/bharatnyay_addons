# -*- coding: utf-8 -*-


def migrate(cr, version):
    from odoo.addons.bharatnyay_core.hooks import purge_bharatnyay_demo_portfolio

    purge_bharatnyay_demo_portfolio(cr)
