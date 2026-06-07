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
        '(extra columns ignored). Tracking No matches postal dispatch POD, then loan POD.',
    )
    dry_run = fields.Boolean(string='Dry run (preview only)', default=True)

    def _parse_date(self, val):
        val = (val or '').strip()
        if not val:
            return False
        for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
        return False

    def _find_dispatch_for_tracking(self, track):
        Dispatch = self.env['bharat.loan.postal.dispatch']
        dispatches = Dispatch.search([('pod', '=', track)])
        if len(dispatches) == 1:
            return dispatches
        loans = self.env['bharat.loan'].search([('pod', '=', track)])
        if len(loans) == 1:
            loan = loans[0]
            open_dispatches = Dispatch.search([
                ('loan_id', '=', loan.id),
                ('post_office_status_id.triggers_billing', '=', False),
            ], order='id')
            if open_dispatches:
                return open_dispatches[:1]
            any_dispatch = Dispatch.search([('loan_id', '=', loan.id)], order='id', limit=1)
            if any_dispatch:
                return any_dispatch
        return Dispatch.browse()

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

        updated = 0
        skipped = []
        preview_lines = []

        for row in reader:
            track_col = headers['tracking no']
            track = (row.get(track_col) or '').strip()
            if not track:
                continue
            dispatch = self._find_dispatch_for_tracking(track)
            if not dispatch:
                skipped.append(track)
                continue
            disp = self._parse_date(row.get(headers['dispatch date']))
            stat = (row.get(headers['delivery status']) or '').strip()
            deliv = self._parse_date(row.get(headers['delivery date']))
            loan = dispatch.loan_id
            preview_lines.append(
                '%s → %s / %s (%s)' % (
                    track,
                    loan.loan_number,
                    dispatch.document_label,
                    stat or '-',
                )
            )
            if not self.dry_run:
                if not dispatch.pod:
                    dispatch.pod = track
                dispatch.apply_postal_import_row(disp, deliv, stat)
                loan.message_post(
                    body=_(
                        'Postal import updated <b>%(doc)s</b> tracking '
                        '<b>%(track)s</b> — %(status)s.'
                    ) % {
                        'doc': escape(dispatch.document_label or ''),
                        'track': escape(track),
                        'status': escape(stat or dispatch.post_office_status_id.name or '-'),
                    },
                )
            updated += 1

        pieces = [
            _('Matched rows: %s') % updated,
            _('Unmatched tracking numbers: %s') % len(skipped),
        ]
        if preview_lines[:20]:
            pieces.append('\n'.join(preview_lines[:20]))
        if self.dry_run:
            pieces.append(_('Dry run — untick “Dry run” and run again to write records.'))

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
