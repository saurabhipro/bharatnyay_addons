{
    'name': 'BharatNyay Accounting',
    'version': '18.0.1.0.0',
    'summary': 'Arbitration billing invoices and consolidated invoicing',
    'category': 'Accounting/Accounting',
    'author': 'BharatNyay Team',
    'depends': ['bharatnyay_core', 'account', 'account_payment'],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/arbitration_invoices_views.xml',
        'views/invoice_wizard_views.xml',
        'views/arbitration_billing_account_views.xml',
        'reports/arbitration_invoice_annexure_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bharatnyay_core/static/src/consolidated_invoice_wizard/consolidated_invoice_wizard.scss',
        ],
    },
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
