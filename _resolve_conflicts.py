#!/usr/bin/env python3
"""Resolve git stash merge conflicts by keeping stashed side + upstream-only extras."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = [
    'bharatnyay_core/__manifest__.py',
    'bharatnyay_core/models/loan.py',
    'bharatnyay_core/models/arbitration_billing.py',
    'bharatnyay_core/models/ir_actions_report.py',
    'bharatnyay_core/wizards/arbitration_invoice_loader_wizard.py',
    'bharatnyay_core/wizards/loan_hearing_wizards.py',
    'bharatnyay_core/views/loan_views.xml',
    'bharatnyay_core/views/arbitration_billing_views.xml',
    'bharatnyay_core/static/src/dashboard/dashboard_helpers.js',
]


def split_conflict(text):
    pattern = r'<<<<<<< Updated upstream\n(.*?)=======\n(.*?)>>>>>>> Stashed changes\n?'
    match = re.match(pattern, text, re.S)
    if not match:
        return None
    return match.group(1), match.group(2)


INTERIM_ORDER_REPORT_BLOCK = """    _INTERIM_ORDER_REPORT_NAMES = frozenset({
        'bharatnyay_core.report_bharat_loan_interim_order_document',
        'bharatnyay_core.report_bharat_interim_award_wizard_draft',
    })

    @api.model
    def _bharat_interim_order_date_labels(self, report, docids, data):
        \"\"\"QWeb context for interim-order PDFs (no report.* model — names exceed PG limit).\"\"\"
        docs = data.get('docs')
        if not docs:
            docs = self.env[report.model].browse(docids).exists()
        labels = {}
        date_field = (
            'create_date'
            if report.model == 'bharat.loan.interim.award.wizard'
            else 'order_date'
        )
        for doc in docs:
            value = doc[date_field]
            labels[doc.id] = (
                format_datetime(doc.env, value, dt_format='medium') if value else '—'
            )
        return labels

    def _get_rendering_context(self, report, docids, data):
        data = super()._get_rendering_context(report, docids, data)
        report_name = report.report_name or ''
        if report_name in self._INTERIM_ORDER_REPORT_NAMES:
            data.setdefault(
                'interim_order_date_labels',
                self._bharat_interim_order_date_labels(report, docids, data),
            )
        return data

"""


def merge_manifest(upstream, stashed):
    merged = stashed
    if 'interim_order_form/interim_order_form.scss' in upstream and \
            'interim_order_form/interim_order_form.scss' not in merged:
        merged = merged.replace(
            "            'bharatnyay_core/static/src/interim_award_wizard/interim_award_wizard.scss',\n",
            "            'bharatnyay_core/static/src/interim_award_wizard/interim_award_wizard.scss',\n"
            "            'bharatnyay_core/static/src/interim_order_form/interim_order_form.scss',\n",
        )
    return merged


def merge_ir_actions_report(upstream, stashed):
    if '_INTERIM_ORDER_REPORT_NAMES' in stashed:
        return stashed
    if 'from odoo.tools.misc import format_datetime' not in stashed:
        stashed = stashed.replace(
            'from odoo.tools import split_every\n',
            'from odoo.tools import split_every\nfrom odoo.tools.misc import format_datetime\n',
        )
    marker = "class IrActionsReport(models.Model):\n    _inherit = 'ir.actions.report'\n\n"
    if marker not in stashed:
        raise RuntimeError('Unexpected ir_actions_report.py structure')
    return stashed.replace(marker, marker + INTERIM_ORDER_REPORT_BLOCK, 1)


def resolve_file(rel_path):
    path = ROOT / rel_path
    text = path.read_text(encoding='utf-8')
    parts = split_conflict(text)
    if not parts:
        print(f'SKIP (no markers): {rel_path}')
        return False
    upstream, stashed = parts
    if rel_path == 'bharatnyay_core/__manifest__.py':
        resolved = merge_manifest(upstream, stashed)
    elif rel_path == 'bharatnyay_core/models/ir_actions_report.py':
        resolved = merge_ir_actions_report(upstream, stashed)
    else:
        resolved = stashed
    path.write_text(resolved, encoding='utf-8')
    print(f'RESOLVED: {rel_path} ({len(resolved.splitlines())} lines)')
    return True


def main():
    count = 0
    for rel_path in FILES:
        if resolve_file(rel_path):
            count += 1
    print(f'Done: {count} files resolved')


if __name__ == '__main__':
    main()
