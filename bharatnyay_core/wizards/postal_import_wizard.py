# -*- coding: utf-8 -*-
import csv
import io
from datetime import datetime

from markupsafe import escape

from odoo import _, fields, models
from odoo.exceptions import UserError


class BharatPostalTrackingImportWizard(models.TransientModel):
    _name = 'bharat.postal.tracking.import.wizard'
    _description = 'Import postal / POD tracking rows'

    raw_text = fields.Text(
        string='CSV rows',
        required=True,
        help='Include a header row. Columns: Tracking No, Dispatch Date, Delivery Status, Delivery Date '
        '(extra columns ignored). Tracking No is matched to Loan → POD field.',
    )
    dry_run = fields.Boolean(string='Dry run (preview only)', default=True)

    def action_import(self):
        self.ensure_one()
        raw = (self.raw_text or '').strip()
        if not raw:
            raise UserError(_('Paste at least the header row and one data row.'))
        reader = csv.DictReader(io.StringIO(raw))
        headers = {k.strip().lower(): k for k in (reader.fieldnames or [])}
        need = ['tracking no', 'dispatch date', 'delivery status', 'delivery date']
        for h in need:
            if h not in headers:
                raise UserError(_('Missing column: %s') % h.title())

        Loan = self.env['bharat.loan']
        updated = 0
        skipped = []
        preview_lines = []

        def parse_date(val):
            val = (val or '').strip()
            if not val:
                return False
            for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
                try:
                    return datetime.strptime(val, fmt).date()
                except ValueError:
                    continue
            return False

        for row in reader:
            track_col = headers['tracking no']
            track = (row.get(track_col) or '').strip()
            if not track:
                continue
            loans = Loan.search([('pod', '=', track)], limit=2)
            if len(loans) != 1:
                skipped.append(track)
                continue
            loan = loans[0]
            disp = parse_date(row.get(headers['dispatch date']))
            stat = (row.get(headers['delivery status']) or '').strip()
            deliv = parse_date(row.get(headers['delivery date']))
            preview_lines.append('%s → %s (%s)' % (track, loan.loan_number, stat or '-'))
            if not self.dry_run:
                loan.write({
                    'deliver_date': deliv or disp or loan.deliver_date,
                    'deliver_status': stat or loan.deliver_status,
                })
                loan.message_post(
                    body=_('Postal import updated POD tracking <b>%s</b>.') % escape(track),
                )
            updated += 1

        pieces = [
            _('Matched rows: %s') % updated,
            _('Unmatched tracking numbers: %s') % len(skipped),
        ]
        if preview_lines[:20]:
            pieces.append('\n'.join(preview_lines[:20]))
        if self.dry_run:
            pieces.append(_('Dry run — untick “Dry run” and run again to write loans.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Postal import'),
                'message': '\n'.join(pieces),
                'sticky': True,
                'type': 'success' if updated else 'warning',
            },
        }
