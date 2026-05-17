{
    "name": "BharatNyay Website",
    "version": "18.0.1.1.0",
    "icon": "/bharatnyay_website/static/description/icon.png",
    "summary": "Public marketing site & landing experience for BharatNyay ODR",
    "description": """
        Rich landing page (hero, stats, features, stakeholders, testimonials, CTA, footer)
        inspired by BharatNyay brand mockups and public ODR storytelling for
        mediation, arbitration, conciliation, and negotiation workflows.

        Also exposes ``/bharat/cases`` for signed-in users to preview portfolio rows that match
        their contact name (demo behaviour — refine per deployment).
    """,
    "category": "Website/Website",
    "author": "BharatNyay Team",
    "depends": ["bharatnyay_core", "website"],
    "data": [
        "data/website_menu_data.xml",
        "views/website_layout.xml",
        "views/bn_fragments_public.xml",
        "views/homepage_templates.xml",
        "views/about_templates.xml",
        "views/odr_what_templates.xml",
        "views/odr_proceedings_templates.xml",
        "views/odr_model_clause_templates.xml",
        "views/odr_standards_templates.xml",
        "views/odr_menu_extended_templates.xml",
        "views/features_page_templates.xml",
        "views/how_it_works_templates.xml",
        "views/portal_cases_templates.xml",
        "views/bn_notice_microsite_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "bharatnyay_website/static/src/scss/style.scss",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
