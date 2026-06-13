# -*- coding: utf-8 -*-
"""Master metadata for interim order types (purpose, typical loan, passed by, directions)."""

from markupsafe import escape

INTERIM_ORDER_PASSED_BY_SELECTION = [
    ('court', 'Court'),
    ('arbitrator', 'Arbitrator'),
    ('court_arbitrator', 'Court / Arbitrator'),
    ('mostly_court', 'Mostly Court'),
]

INTERIM_ORDER_TYPE_SELECTION = [
    ('bank_account_freeze', 'Bank Account Freeze / Attachment'),
    ('asset_disclosure', 'Asset Disclosure Order'),
    ('security_deposit', 'Security Deposit / Furnishing Security'),
    ('vehicle_repossession', 'Vehicle Repossession Order'),
    ('property_status_quo', 'Property Status Quo Order'),
    ('appointment_receiver', 'Appointment of Receiver'),
    ('salary_withholding', 'Salary Withholding / Garnishee Direction'),
    ('restraining_disposal', 'Restraining Disposal of Assets'),
    ('attachment_receivables', 'Attachment of Receivables'),
    ('preservation_evidence', 'Preservation of Electronic Evidence'),
    ('interim_stay', 'Interim Stay Order'),
]

INTERIM_ORDER_TYPE_META = {
    'bank_account_freeze': {
        'purpose': 'Secure disputed amount',
        'typical_loan_type': 'Personal loan, credit card, business loan',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Freeze account, maintain balance, restrict withdrawals',
    },
    'asset_disclosure': {
        'purpose': 'Identify recoverable assets',
        'typical_loan_type': 'All loan types',
        'passed_by': 'court_arbitrator',
        'common_directions': 'File affidavit of assets, disclose bank/property details',
    },
    'security_deposit': {
        'purpose': 'Protect lender claim during arbitration',
        'typical_loan_type': 'Large-value loans, business loans',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Deposit amount, furnish bank guarantee',
    },
    'vehicle_repossession': {
        'purpose': 'Recover hypothecated vehicle',
        'typical_loan_type': 'Auto loan, equipment finance',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Seizure/repossession of vehicle',
    },
    'property_status_quo': {
        'purpose': 'Prevent transfer of mortgaged property',
        'typical_loan_type': 'Home loan, LAP',
        'passed_by': 'court_arbitrator',
        'common_directions': 'No sale, no transfer, no third-party rights',
    },
    'appointment_receiver': {
        'purpose': 'Preserve/manage secured assets',
        'typical_loan_type': 'Commercial loans, mortgage disputes',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Receiver takes custody/control of asset',
    },
    'salary_withholding': {
        'purpose': 'Recover dues through third-party payments',
        'typical_loan_type': 'Personal loan, salary-backed loan',
        'passed_by': 'mostly_court',
        'common_directions': 'Employer/payment diversion directions',
    },
    'restraining_disposal': {
        'purpose': 'Prevent borrower from disposing collateral',
        'typical_loan_type': 'MSME, inventory finance',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Restriction on sale/transfer of inventory or machinery',
    },
    'attachment_receivables': {
        'purpose': 'Secure business cash flow',
        'typical_loan_type': 'MSME/business loans',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Divert customer receivables into escrow',
    },
    'preservation_evidence': {
        'purpose': 'Preserve digital records/data',
        'typical_loan_type': 'Fintech/NBFC disputes',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Preserve logs, accounting data, platform records',
    },
    'interim_stay': {
        'purpose': 'Stay coercive recovery action pending adjudication',
        'typical_loan_type': 'All loan types',
        'passed_by': 'court_arbitrator',
        'common_directions': 'Stay repossession, stay recovery, stay coercive action',
    },
}


def interim_order_meta(order_type):
    """Return purpose / loan type / passed by / directions for an interim order type code."""
    return dict(INTERIM_ORDER_TYPE_META.get(order_type, {}))


def interim_order_type_label(order_type):
    mapping = dict(INTERIM_ORDER_TYPE_SELECTION)
    return mapping.get(order_type, order_type or '')


def interim_order_passed_by_label(passed_by):
    mapping = dict(INTERIM_ORDER_PASSED_BY_SELECTION)
    return mapping.get(passed_by, passed_by or '')


def _format_amount(loan, amount):
    if not amount:
        return ''
    currency = loan.currency_id if loan else None
    symbol = (currency.symbol or '') if currency else '₹'
    return '%s %s' % (symbol, amount)


def render_interim_order_draft_html(
    order_type,
    loan,
    *,
    amount=0.0,
    additional_notes='',
    common_directions='',
    purpose='',
):
    """Build editable HTML body for an interim order draft from type metadata + case data."""
    meta = interim_order_meta(order_type)
    type_label = interim_order_type_label(order_type)
    purpose_text = (purpose or meta.get('purpose') or '').strip()
    directions_text = (common_directions or meta.get('common_directions') or '').strip()
    direction_items = [
        item.strip()
        for chunk in directions_text.replace(';', ',').split(',')
        for item in [chunk]
        if item.strip()
    ]
    if not direction_items:
        direction_items = ['(Add directions in the draft editor.)']

    claimant = (loan.company_id.name if loan and loan.company_id else '') or 'Claimant'
    respondent = (loan.customer_name if loan else '') or 'Respondent'
    loan_number = (loan.loan_number if loan else '') or '—'
    case_number = (loan.case_number if loan else '') or '—'

    amount_html = ''
    if amount:
        amount_html = (
            '<p style="margin: 0 0 10px 0; text-align: justify; line-height: 1.32;">'
            '<strong>Interim amount directed:</strong> %s</p>'
        ) % escape(_format_amount(loan, amount))

    notes_html = ''
    if (additional_notes or '').strip():
        notes_html = (
            '<p style="margin: 0 0 6px 0; font-weight: 700;">Additional directions / rationale:</p>'
            '<p style="margin: 0 0 10px 0; white-space: pre-wrap; line-height: 1.32;">%s</p>'
        ) % escape(additional_notes.strip())

    items_html = ''.join(
        '<li style="margin-bottom: 4px;">%s</li>' % escape(item)
        for item in direction_items
    )

    purpose_html = ''
    if purpose_text:
        purpose_html = (
            '<p style="margin: 0 0 8px 0; line-height: 1.32;">'
            '<strong>Nature / purpose:</strong> %s</p>'
        ) % escape(purpose_text)

    return (
        '<h3 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 700; '
        'text-transform: uppercase; letter-spacing: 0.2px;">%s</h3>'
        '%s'
        '<p style="margin: 0 0 6px 0; text-align: justify; line-height: 1.32;">'
        'Upon consideration of the pleadings, submissions, and documents placed on record '
        'in Loan Account No. <strong>%s</strong> (Case ID <strong>%s</strong>) between '
        '<strong>%s</strong> and <strong>%s</strong>, the Tribunal is satisfied that '
        'a prima facie case exists in favour of the Claimant.</p>'
        '<p style="margin: 0 0 10px 0; text-align: justify; line-height: 1.32;">'
        'Accordingly, it is <strong>ORDERED</strong> that:</p>'
        '<ol style="margin: 0 0 10px 0; padding-left: 22px; line-height: 1.32;">%s</ol>'
        '%s%s'
        '<p style="margin: 0; text-align: justify; line-height: 1.32;">'
        'This Interim Order shall remain in force till further orders or final disposal '
        'of the arbitration proceedings.</p>'
    ) % (
        escape(type_label),
        purpose_html,
        escape(loan_number),
        escape(case_number),
        escape(claimant),
        escape(respondent),
        items_html,
        amount_html,
        notes_html,
    )
