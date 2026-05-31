# -*- coding: utf-8 -*-
import base64
import io
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools.xlsx_reader import excel_serial_to_date, read_xlsx_rows

_CONTACT_FROM_ADDRESS_RE = re.compile(r'Contact\s*No\.?\s*[-:]\s*(\d[\d\s]{8,14}\d)', re.I)


def _normalize_header(value):
    if value in (None, False):
        return ''
    text = ' '.join(str(value).replace('\n', ' ').replace('\r', ' ').split()).strip().lower()
    return re.sub(r'\s*/\s*', '/', text)


EXCEL_COLUMN_MAP = {
    'loan number': ('loan_number', 'char'),
    'customer name': ('customer_name', 'char'),
    'followup_mode': ('followup_mode', 'char'),
    'branch': ('branch', 'char'),
    'location': ('location', 'char'),
    'region': ('region', 'char'),
    'state': ('borrower_state', 'char'),
    'product_classi': ('product_classification', 'char'),
    'product_class': ('product_classification', 'char'),
    'product classification': ('product_classification', 'char'),
    'write off': ('write_off', 'char'),
    'current_pos': ('current_pos', 'float'),
    'lok adalat/conciliation': ('lok_adalat_conciliation', 'char'),
    'lok adalat/conciliation date': ('lok_adalat_date', 'date'),
    'lok adalat/conciliation location': ('lok_adalat_location', 'char'),
    'lok adalat/conciliation location address': ('lok_adalat_location_address', 'text'),
    'law firm name': ('law_firm_name', 'char'),
    'financed amt': ('financed_amount', 'float'),
    'date of disbursment': ('disbursement_date', 'date'),
    'date of disbursement': ('disbursement_date', 'date'),
    'product': ('product', 'char'),
    'contact no of colletion person.': ('borrower_phone', 'char'),
    'contact no of collection person.': ('borrower_phone', 'char'),
    'acm name': ('acm_name', 'char'),
    'follow up mode': ('follow_up_mode_alt', 'char'),
    'complete address along with customer name': ('borrower_address', 'text'),
    'legal fpr': ('legal_fpr', 'float'),
    'claim amt': ('claim_amount', 'float'),
    'notice handover date': ('notice_hand', 'notice_hand'),
    'pod': ('pod', 'char'),
    'deliver date': ('deliver_date', 'date'),
    'deliver status': ('deliver_status', 'char'),
}


class BharatLoanPortfolioImportWizard(models.TransientModel):
    _name = 'bharat.loan.portfolio.import.wizard'
    _description = 'Import portfolio / Lok Adalat Excel into cases'

    data_file = fields.Binary(string='Excel file (.xlsx)', required=True)
    filename = fields.Char(string='Filename')
    update_existing = fields.Boolean(
        string='Update existing cases (same loan number)',
        default=True,
        help='When checked, rows whose loan number already exists refresh that case. '
        'When unchecked, existing loan numbers are skipped and only new ones are imported.',
    )
    dry_run = fields.Boolean(
        string='Preview only (do not write)',
        default=False,
    )
    import_state = fields.Selection(
        [
            ('idle', 'Ready'),
            ('done', 'Completed'),
        ],
        string='Status',
        default='idle',
        readonly=True,
    )
    result_summary = fields.Text(string='Result', readonly=True)
    error_log = fields.Text(
        string='Failed rows',
        readonly=True,
        help='Only rows that could not be imported. All other rows were saved.',
    )

    @staticmethod
    def _parse_float(value):
        if value in (None, '', False):
            return False
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(',', '')
        if not text:
            return False
        try:
            return float(text)
        except ValueError:
            return False

    @staticmethod
    def _normalize_loan_number(value):
        if value in (None, '', False):
            return ''
        if isinstance(value, float) and value == int(value):
            value = int(value)
        return str(value).strip()

    @classmethod
    def _coerce_cell(cls, value, kind):
        if value in (None, '', False):
            return False
        if kind == 'char':
            if isinstance(value, float) and value == int(value):
                value = int(value)
            text = str(value).strip()
            return text or False
        if kind == 'text':
            text = str(value).strip()
            return text or False
        if kind == 'float':
            parsed = cls._parse_float(value)
            return parsed if parsed is not False else False
        if kind == 'date':
            parsed = excel_serial_to_date(value)
            return parsed or False
        if kind == 'notice_hand':
            parsed = excel_serial_to_date(value)
            if parsed:
                return parsed.strftime('%d-%m-%Y')
            text = str(value).strip()
            return text or False
        return value

    @classmethod
    def _build_column_index_map(cls, header_row):
        mapping = {}
        unknown = []
        for idx, header in enumerate(header_row):
            key = _normalize_header(header)
            if not key:
                continue
            spec = EXCEL_COLUMN_MAP.get(key)
            if not spec:
                unknown.append(header)
                continue
            mapping[idx] = spec
        return mapping, unknown

    @classmethod
    def _row_to_vals(cls, row, column_map):
        vals = {}
        for idx, (field_name, kind) in column_map.items():
            if idx >= len(row):
                continue
            coerced = cls._coerce_cell(row[idx], kind)
            if coerced is not False and coerced is not None:
                vals[field_name] = coerced
        return vals

    @staticmethod
    def _enrich_borrower_contact(vals):
        phone = vals.get('borrower_phone')
        if phone not in (None, '', False):
            if isinstance(phone, float) and phone == int(phone):
                phone = int(phone)
            vals['borrower_phone'] = re.sub(r'\D', '', str(phone)) or False
            return
        address = vals.get('borrower_address') or ''
        match = _CONTACT_FROM_ADDRESS_RE.search(str(address))
        if match:
            vals['borrower_phone'] = re.sub(r'\s+', '', match.group(1))

    def _parse_workbook(self):
        if not self.data_file:
            raise UserError(_('Upload an Excel (.xlsx) file.'))
        try:
            raw = base64.b64decode(self.data_file)
        except Exception as exc:
            raise UserError(_('Could not decode the uploaded file.')) from exc
        if not raw:
            raise UserError(_('The uploaded file is empty.'))
        try:
            rows = read_xlsx_rows(io.BytesIO(raw))
        except Exception as exc:
            raise UserError(_('Could not read the Excel workbook: %s') % exc) from exc
        if not rows:
            raise UserError(_('The workbook has no rows.'))
        column_map, unknown_headers = self._build_column_index_map(rows[0])
        if 'loan_number' not in {spec[0] for spec in column_map.values()}:
            raise UserError(
                _('Missing required column “Loan Number”. Found headers: %s')
                % ', '.join(str(h) for h in rows[0] if h)
            )
        return rows[1:], column_map, unknown_headers

    def action_import(self):
        self.ensure_one()
        data_rows, column_map, unknown_headers = self._parse_workbook()

        Loan = self.env['bharat.loan'].with_context(from_import=True)
        created = 0
        updated = 0
        skipped_existing = 0
        skipped_blank = 0
        locked = 0
        errors = []
        last_batch = False

        for row_idx, row in enumerate(data_rows, start=2):
            vals = self._row_to_vals(row, column_map)
            loan_number = self._normalize_loan_number(vals.get('loan_number'))
            if not loan_number:
                skipped_blank += 1
                continue
            vals['loan_number'] = loan_number
            self._enrich_borrower_contact(vals)

            existing = Loan.search([('loan_number', '=', loan_number)], limit=1)

            if existing:
                if existing.is_case_locked:
                    locked += 1
                    errors.append(
                        _('Row %(row)s | Loan %(loan)s | Case locked (Final Award) — skipped')
                        % {'row': row_idx, 'loan': loan_number}
                    )
                    continue
                if not self.update_existing:
                    skipped_existing += 1
                    continue
                if self.dry_run:
                    updated += 1
                    continue
                try:
                    existing.write(vals)
                    updated += 1
                except Exception as exc:
                    errors.append(
                        _('Row %(row)s | Loan %(loan)s | %(error)s')
                        % {'row': row_idx, 'loan': loan_number, 'error': exc}
                    )
                continue

            if self.dry_run:
                created += 1
                continue
            try:
                loan = Loan.create(vals)
                created += 1
                if loan.batch_number:
                    last_batch = loan.batch_number
            except Exception as exc:
                errors.append(
                    _('Row %(row)s | Loan %(loan)s | %(error)s')
                    % {'row': row_idx, 'loan': loan_number, 'error': exc}
                )

        imported_ok = created + updated
        if self.dry_run:
            headline = _('PREVIEW ONLY — no data was saved.')
        elif errors:
            headline = _('Import finished with errors — %(ok)s row(s) saved, %(bad)s row(s) failed.')
            headline = headline % {'ok': imported_ok, 'bad': len(errors)}
        else:
            headline = _('Import completed successfully — %(ok)s row(s) saved.') % {'ok': imported_ok}

        summary_lines = [
            headline,
            '',
            _('File: %s') % (self.filename or _('(unnamed)')),
            _('Rows in sheet: %s') % len(data_rows),
        ]
        if self.dry_run:
            summary_lines.extend([
                _('Would create: %s') % created,
                _('Would update: %s') % updated,
                _('Would skip (loan already exists, update off): %s') % skipped_existing,
            ])
        else:
            summary_lines.extend([
                _('Created: %s') % created,
                _('Updated: %s') % updated,
                _('Skipped (loan already exists, update off): %s') % skipped_existing,
            ])
        summary_lines.extend([
            _('Skipped (blank loan number): %s') % skipped_blank,
            _('Skipped (case locked): %s') % locked,
            _('Failed: %s') % len(errors),
        ])
        if last_batch:
            summary_lines.append(_('New batch number: %s') % last_batch)
        if unknown_headers:
            summary_lines.append(
                _('Ignored columns (no case field): %s')
                % ', '.join(str(h) for h in unknown_headers if h)
            )
        if self.dry_run:
            summary_lines.extend([
                '',
                _('Uncheck “Preview only” and click Import again to save data.'),
            ])
        elif imported_ok and not errors:
            summary_lines.extend([
                '',
                _('Open Cases to review imported records.'),
            ])
        elif imported_ok and errors:
            summary_lines.extend([
                '',
                _('Correct rows are already saved. Fix failed rows in Excel and re-import, '
                  'or update those cases manually.'),
            ])

        self.write({
            'import_state': 'done' if not self.dry_run else 'idle',
            'result_summary': '\n'.join(summary_lines),
            'error_log': '\n'.join(errors) if errors else False,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Portfolio import'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_cases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cases'),
            'res_model': 'bharat.loan',
            'view_mode': 'list,form',
            'target': 'current',
        }
