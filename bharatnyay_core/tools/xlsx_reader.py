# -*- coding: utf-8 -*-
"""Minimal XLSX reader (stdlib only) for portfolio import wizards."""

import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_CELL_REF_RE = re.compile(r'^([A-Z]+)(\d+)$')
_DEFAULT_MAX_ROWS = 100_000
_MAX_SHEET_ROW = 1_048_576


def _col_index(col_letters):
    idx = 0
    for ch in col_letters:
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def _load_shared_strings(zf):
    try:
        root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    except KeyError:
        return []
    strings = []
    for si in root.findall('m:si', _NS):
        parts = []
        for node in si.findall('.//m:t', _NS):
            parts.append(node.text or '')
        strings.append(''.join(parts))
    return strings


def _sheet_path(zf):
    for name in ('xl/worksheets/sheet1.xml', 'xl/worksheets/Sheet1.xml'):
        if name in zf.namelist():
            return name
    for name in zf.namelist():
        if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
            return name
    raise ValueError('No worksheet found in workbook.')


def _cell_value(cell, shared_strings):
    cell_type = cell.get('t')
    value_node = cell.find('m:v', _NS)
    if value_node is None:
        inline = cell.find('m:is/m:t', _NS)
        if inline is not None:
            return inline.text
        return None
    raw = value_node.text
    if cell_type == 's':
        return shared_strings[int(raw)]
    if cell_type == 'b':
        return raw == '1'
    if raw is None:
        return None
    if cell_type in (None, 'n'):
        try:
            if '.' in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw
    return raw


def _parse_row_element(row_el, shared_strings):
    row_num = int(row_el.get('r', '0') or 0)
    cells = {}
    for cell in row_el.findall('m:c', _NS):
        ref = cell.get('r') or ''
        match = _CELL_REF_RE.match(ref)
        if not match:
            continue
        col_idx = _col_index(match.group(1))
        cells[col_idx] = _cell_value(cell, shared_strings)
    return row_num, cells


def read_xlsx_rows(file_bytes, *, max_rows=None):
    """Return list of rows; each row is a list of cell values (column-aligned).

    Only rows that contain at least one populated cell are returned (no dense fill
    between distant row numbers — avoids MemoryError on sheets with stray formatting
    on row 1,048,576).
    """
    row_cap = max_rows if max_rows is not None else _DEFAULT_MAX_ROWS
    parsed_rows = []
    max_col = 0

    try:
        zf = zipfile.ZipFile(file_bytes)
    except zipfile.BadZipFile as exc:
        raise ValueError(
            'File is not a valid .xlsx workbook (ZIP). Save as Excel .xlsx, not .xls.'
        ) from exc

    with zf:
        shared_strings = _load_shared_strings(zf)
        sheet_path = _sheet_path(zf)

        # Stream-parse the sheet so we never build a DOM for the whole worksheet.
        for event, elem in ET.iterparse(zf.open(sheet_path), events=('end',)):
            if not elem.tag.endswith('}row'):
                continue
            row_num, cells = _parse_row_element(elem, shared_strings)
            elem.clear()
            if row_num > _MAX_SHEET_ROW:
                continue
            if not cells:
                continue
            if row_num > row_cap:
                raise ValueError(
                    'Worksheet row %s exceeds the import limit (%s rows). '
                    'Remove stray data/formatting far below your data range.'
                    % (row_num, row_cap)
                )
            max_col = max(max_col, max(cells))
            parsed_rows.append((row_num, cells))

    if not parsed_rows:
        return []

    if len(parsed_rows) > row_cap:
        raise ValueError('Too many populated rows (%s). Maximum is %s.' % (len(parsed_rows), row_cap))

    parsed_rows.sort(key=lambda item: item[0])
    return [
        [cells.get(col) for col in range(max_col + 1)]
        for _row_num, cells in parsed_rows
    ]


def excel_serial_to_date(serial):
    """Convert Excel date serial to ``datetime.date`` (1900 date system)."""
    if serial in (None, '', False):
        return None
    if isinstance(serial, datetime):
        return serial.date()
    if hasattr(serial, 'date') and not isinstance(serial, (int, float, str)):
        return serial.date()
    if isinstance(serial, str):
        text = serial.strip()
        if not text:
            return None
        for fmt in (
            '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
            '%d/%b/%y', '%d/%b/%Y', '%d-%b-%Y', '%d-%b-%y',
        ):
            try:
                return datetime.strptime(text[:11], fmt).date()
            except ValueError:
                continue
        try:
            serial = float(text)
        except ValueError:
            return None
    if isinstance(serial, (int, float)):
        whole = int(serial)
        if whole <= 0:
            return None
        return (datetime(1899, 12, 30) + timedelta(days=whole)).date()
    return None
