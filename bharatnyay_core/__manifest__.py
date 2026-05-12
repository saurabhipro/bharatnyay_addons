{
    'name': 'BharatNyay Core',
    'version': '18.0.20.0.0',
    'icon': '/bharatnyay_core/static/description/icon.png',
    'summary': 'Loan portfolio aligned to Excel import template',
    'description': """
        Loan sheet model (`bharat.loan`) with masters for region, state, branch, location,
        product class, write-off and law firm. Import from spreadsheet via List ▸ Favorites ▸ Import Records.
    """,
    'category': 'Operations/Disputes',
    'author': 'BharatNyay Team',
    'depends': ['web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/loan_sequence_data.xml',
        'data/notification_template_data.xml',
        'views/master_views.xml',
        'views/user_role_views.xml',
        'views/notification_template_views.xml',
        'views/loan_notice_wizard_views.xml',
        'views/loan_notice_response_wizard_views.xml',
        'views/loan_hearing_wizard_views.xml',
        'reports/loan_notice_reports.xml',
        'views/loan_views.xml',
        'views/dashboard_action.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bharatnyay_core/static/src/dashboard/bharatnyay_dashboard.scss',
            'bharatnyay_core/static/src/loan_form/loan_form.scss',
            'bharatnyay_core/static/src/dashboard/bharatnyay_dashboard.xml',
            'bharatnyay_core/static/src/dashboard/bharatnyay_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
