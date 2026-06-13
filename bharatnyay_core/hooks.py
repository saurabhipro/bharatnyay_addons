# -*- coding: utf-8 -*-
"""Module install/upgrade hooks."""


def pre_init_hook(cr):
    """Clean milestone_code selection metadata before field-type migrations.

    Odoo 18 raises AttributeError when unlinking ir.model.fields.selection rows
    after milestone_code was briefly defined as Char (Selection.ondelete missing).
    """
    cr.execute(
        """
        DELETE FROM ir_model_fields_selection
        WHERE field_id IN (
            SELECT id FROM ir_model_fields
            WHERE model = 'bharat.loan' AND name = 'milestone_code'
        )
        """
    )
    cr.execute(
        """
        UPDATE ir_model_fields
        SET ttype = 'selection'
        WHERE model = 'bharat.loan'
          AND name = 'milestone_code'
          AND ttype = 'char'
        """
    )


def post_init_hook(env):
    """Point all internal users at their BharatNyay dashboard on install/upgrade."""
    users = env['res.users'].sudo().search([
        ('share', '=', False),
        ('active', '=', True),
    ])
    users._sync_bharat_home_action()
