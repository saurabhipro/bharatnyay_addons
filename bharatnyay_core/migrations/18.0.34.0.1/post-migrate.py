# -*- coding: utf-8 -*-


def migrate(cr, version):
    from odoo.addons.bharatnyay_core.hooks import cleanup_orphan_ir_model_data

    cleanup_orphan_ir_model_data(cr)
