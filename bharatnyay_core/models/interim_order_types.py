# -*- coding: utf-8 -*-
"""Master metadata for interim order types (purpose, typical loan, passed by, directions)."""

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
