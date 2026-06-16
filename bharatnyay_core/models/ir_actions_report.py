<<<<<<< Updated upstream
# -*- coding: utf-8 -*-
import base64
import io
import logging
import os
import resource
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing

import lxml.html

from odoo import _, api, models
from odoo.addons.base.models.ir_actions_report import _get_wkhtmltopdf_bin, _split_table
from odoo.exceptions import UserError
from odoo.tools import split_every
from odoo.tools.misc import format_datetime

from ..tools.pdf_render import read_fast_mode, read_merge_chunk, read_parallel_workers

_logger = logging.getLogger(__name__)


def _bharat_run_wkhtmltopdf_subprocess(command_args, bodies, header, footer):
    """Convert prepared HTML to PDF via wkhtmltopdf (no ORM — safe in thread pool)."""
    files_command_args = []
    temporary_files = []

    if header:
        head_file_fd, head_file_path = tempfile.mkstemp(suffix='.html', prefix='report.header.tmp.')
        with closing(os.fdopen(head_file_fd, 'wb')) as head_file:
            head_file.write(header.encode())
        temporary_files.append(head_file_path)
        files_command_args.extend(['--header-html', head_file_path])
    if footer:
        foot_file_fd, foot_file_path = tempfile.mkstemp(suffix='.html', prefix='report.footer.tmp.')
        with closing(os.fdopen(foot_file_fd, 'wb')) as foot_file:
            foot_file.write(footer.encode())
        temporary_files.append(foot_file_path)
        files_command_args.extend(['--footer-html', foot_file_path])

    paths = []
    for i, body in enumerate(bodies):
        prefix = '%s%d.' % ('report.body.tmp.', i)
        body_file_fd, body_file_path = tempfile.mkstemp(suffix='.html', prefix=prefix)
        with closing(os.fdopen(body_file_fd, 'wb')) as body_file:
            if len(body) < 4 * 1024 * 1024:
                body_file.write(body.encode())
            else:
                tree = lxml.html.fromstring(body)
                _split_table(tree, 500)
                body_file.write(lxml.html.tostring(tree))
        paths.append(body_file_path)
        temporary_files.append(body_file_path)

    pdf_report_fd, pdf_report_path = tempfile.mkstemp(suffix='.pdf', prefix='report.tmp.')
    os.close(pdf_report_fd)
    temporary_files.append(pdf_report_path)

    try:
        wkhtmltopdf = (
            [_get_wkhtmltopdf_bin()]
            + list(command_args)
            + files_command_args
            + paths
            + [pdf_report_path]
        )
        process = subprocess.Popen(
            wkhtmltopdf,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
        )
        _out, err = process.communicate()

        if process.returncode not in (0, 1):
            if process.returncode == -11:
                message = _(
                    'Wkhtmltopdf failed (error code: %(error_code)s). Memory limit too low or '
                    'maximum file number of subprocess reached. Message : %(message)s',
                    error_code=process.returncode,
                    message=err[-1000:],
                )
            else:
                message = _(
                    'Wkhtmltopdf failed (error code: %(error_code)s). Message: %(message)s',
                    error_code=process.returncode,
                    message=err[-1000:],
                )
            _logger.warning(message)
            raise UserError(message)
        if err:
            _logger.warning('wkhtmltopdf: %s', err)

        with open(pdf_report_path, 'rb') as pdf_document:
            pdf_content = pdf_document.read()
    finally:
        for temporary_file in temporary_files:
            try:
                os.unlink(temporary_file)
            except OSError:
                _logger.error('Error when trying to remove file %s', temporary_file)

    return pdf_content


def _raise_file_descriptor_limit(min_limit=4096):
    """Best-effort raise of soft RLIMIT_NOFILE before bulk wkhtmltopdf runs."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(max(min_limit, soft), hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except (ValueError, OSError):
        pass


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    _INTERIM_ORDER_REPORT_NAMES = frozenset({
        'bharatnyay_core.report_bharat_loan_interim_order_document',
        'bharatnyay_core.report_bharat_interim_award_wizard_draft',
    })

    @api.model
    def _bharat_interim_order_date_labels(self, report, docids, data):
        """QWeb context for interim-order PDFs (no report.* model — names exceed PG limit)."""
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

    @api.model
    def _bharat_icp_get(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _bharat_pdf_parallel_workers(self):
        return read_parallel_workers(self._bharat_icp_get)

    @api.model
    def _bharat_pdf_merge_chunk(self):
        return read_merge_chunk(self._bharat_icp_get)

    @api.model
    def _bharat_pdf_fast_mode(self):
        return read_fast_mode(self._bharat_icp_get)

    @api.model
    def bharat_qr_to_data_uri(self, payload, width=96, height=96):
        """Build an inline QR image for QWeb/PDF (SVG avoids reportlab renderPM/Pillow)."""
        payload = (payload or '').strip()
        if not payload:
            return False

        w, h = int(width), int(height)
        try:
            from reportlab.graphics.barcode import createBarcodeDrawing

            drawing = createBarcodeDrawing(
                'QR',
                value=payload,
                format='svg',
                width=w,
                height=h,
                barBorder=2,
            )
            svg_data = drawing.asString('svg')
            if isinstance(svg_data, str):
                svg_data = svg_data.encode('utf-8')
            encoded = base64.b64encode(svg_data).decode('ascii')
            return 'data:image/svg+xml;base64,%s' % encoded
        except Exception:
            _logger.debug('bharatnyay_core: SVG QR failed, trying PNG barcode()', exc_info=True)

        try:
            png_bytes = self.barcode(
                'QR',
                payload,
                width=w,
                height=h,
                barBorder=2,
                quiet=False,
            )
            return 'data:image/png;base64,%s' % base64.b64encode(png_bytes).decode('ascii')
        except Exception:
            _logger.warning(
                'bharatnyay_core: could not render QR (install reportlab renderPM or use SVG path)',
            )
            return False

    def _is_bharatnyay_pdf_report(self, report_ref=False):
        report = self._get_report(report_ref) if report_ref else self
        name = (report.report_name or report.report_file or '') if report else ''
        return name.startswith('bharatnyay_core.')

    def _normalize_res_ids(self, res_ids):
        if not res_ids:
            return []
        if isinstance(res_ids, int):
            return [res_ids]
        return list(res_ids)

    def _bharat_wkhtmltopdf_user_error(self, err):
        """Turn wkhtmltopdf resource failures into actionable guidance."""
        msg = (err.args[0] if err.args else '') or ''
        low = msg.lower()
        if 'wkhtmltopdf failed' not in low:
            return None
        if any(token in low for token in (
            'error code: -6',
            'error code: -11',
            'too many open files',
            'memory limit',
            'maximum file number',
            'thread pipe',
        )):
            return UserError(
                _('PDF generation failed: wkhtmltopdf ran out of memory or file handles.\n\n'
                  'Bulk prints use parallel workers; if this persists:\n'
                  '1. Lower System Parameter bharat.pdf.parallel_workers (e.g. 3)\n'
                  '2. Restart Odoo and run: pkill -f wkhtmltopdf\n'
                  '3. Start Odoo with: ulimit -n 65536')
            )
        return None

    def _prepare_single_loan_pdf(self, report_ref, res_id, data=None):
        """QWeb HTML + wkhtmltopdf args for one loan (must run on main ORM thread)."""
        additional_context = {'debug': False, 'bharat_light_pdf': True}
        payload = dict(data or {})
        payload.setdefault('debug', False)
        report_sudo = self._get_report(report_ref)
        report_ctx = self.with_context(**additional_context)

        html = report_ctx._render_qweb_html(report_ref, [res_id], data=payload)[0]
        bodies, _html_ids, header, footer, specific_paperformat_args = report_sudo.with_context(
            **additional_context,
        )._prepare_html(html, report_model=report_sudo.model)

        command_args = report_ctx._build_wkhtmltopdf_args(
            report_sudo.get_paperformat(),
            self.env.context.get('landscape'),
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=self.env.context.get('set_viewport_size'),
        )
        return {
            'res_id': res_id,
            'command_args': command_args,
            'bodies': bodies,
            'header': header,
            'footer': footer,
        }

    def _render_loan_pdf_streams_ordered(self, report_ref, res_ids, data=None):
        """Render per-loan PDFs; QWeb sequential, wkhtmltopdf parallel when batch > 1."""
        workers = self._bharat_pdf_parallel_workers()
        prepared = []
        for res_id in res_ids:
            try:
                prepared.append(self._prepare_single_loan_pdf(report_ref, res_id, data=data))
            except UserError as err:
                friendly = self._bharat_wkhtmltopdf_user_error(err)
                if friendly:
                    raise friendly from err
                raise

        def _run_one(pkg):
            return pkg['res_id'], _bharat_run_wkhtmltopdf_subprocess(
                pkg['command_args'],
                pkg['bodies'],
                pkg['header'],
                pkg['footer'],
            )

        if workers <= 1 or len(prepared) <= 1:
            results = {}
            for pkg in prepared:
                res_id, pdf_bytes = _run_one(pkg)
                results[res_id] = pdf_bytes
            return [io.BytesIO(results[res_id]) for res_id in res_ids]

        _raise_file_descriptor_limit(max(4096, workers * 32))
        results = {}
        max_workers = min(workers, len(prepared))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_one, pkg) for pkg in prepared]
            for fut in as_completed(futures):
                res_id, pdf_bytes = fut.result()
                results[res_id] = pdf_bytes

        elapsed = time.time() - t0
        _logger.info(
            'bharatnyay_core: parallel wkhtmltopdf for %s case(s) in %.1fs (%s workers)',
            len(res_ids), elapsed, max_workers,
        )
        return [io.BytesIO(results[res_id]) for res_id in res_ids]

    def _render_bharat_qweb_pdf_merged(self, report_ref, res_ids, data=None):
        """One wkhtmltopdf job per loan (parallel), then merge into one PDF."""
        report = self._get_report(report_ref)
        merge_chunk = self._bharat_pdf_merge_chunk()
        partial_streams = []
        t0 = time.time()

        for chunk_ids in split_every(merge_chunk, res_ids):
            loan_streams = self._render_loan_pdf_streams_ordered(
                report_ref, chunk_ids, data=data,
            )
            if len(loan_streams) == 1:
                partial_streams.append(loan_streams[0])
            else:
                partial_streams.append(self._merge_pdfs(loan_streams))

        if len(partial_streams) == 1:
            pdf_content = partial_streams[0].getvalue()
        else:
            pdf_content = self._merge_pdfs(partial_streams).getvalue()

        _logger.info(
            'bharatnyay_core: merged PDF for %s (%s record(s), report %s) in %.1fs (workers=%s)',
            report.model, len(res_ids), report.report_name, time.time() - t0,
            self._bharat_pdf_parallel_workers(),
        )
        return pdf_content, 'pdf'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        if self._is_bharatnyay_pdf_report(report_ref):
            _raise_file_descriptor_limit()
            ids = self._normalize_res_ids(res_ids)
            if len(ids) > 1:
                try:
                    return self._render_bharat_qweb_pdf_merged(report_ref, ids, data=data)
                except UserError as err:
                    friendly = self._bharat_wkhtmltopdf_user_error(err)
                    if friendly:
                        raise friendly from err
                    raise
            try:
                return super(
                    IrActionsReport,
                    self.with_context(bharat_light_pdf=True),
                )._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
            except UserError as err:
                friendly = self._bharat_wkhtmltopdf_user_error(err)
                if friendly:
                    raise friendly from err
                raise
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    @api.model
    def _build_wkhtmltopdf_args(
            self,
            paperformat_id,
            landscape,
            specific_paperformat_args=None,
            set_viewport_size=False):
        command_args = super()._build_wkhtmltopdf_args(
            paperformat_id,
            landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )
        if not self.env.context.get('bharat_light_pdf'):
            return command_args

        filtered = []
        skip_next = False
        for arg in command_args:
            if skip_next:
                skip_next = False
                continue
            if arg in ('--javascript-delay', '--header-line'):
                skip_next = True
                continue
            filtered.append(arg)

        filtered.extend([
            '--disable-javascript',
            '--no-stop-slow-scripts',
            '--load-error-handling', 'ignore',
            '--load-media-error-handling', 'ignore',
        ])
        if self._bharat_pdf_fast_mode():
            filtered.extend([
                '--lowquality',
                '--image-quality', '60',
            ])
        else:
            filtered.extend([
                '--image-quality', '75',
            ])
        filtered = [a for a in filtered if a != '--disable-smart-shrinking']
        return filtered
=======
# -*- coding: utf-8 -*-
import base64
import io
import logging
import os
import resource
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing

import lxml.html

from odoo import _, api, models
from odoo.addons.base.models.ir_actions_report import _get_wkhtmltopdf_bin, _split_table
from odoo.exceptions import UserError
from odoo.tools import split_every

from ..tools.pdf_render import read_fast_mode, read_merge_chunk, read_parallel_workers

_logger = logging.getLogger(__name__)


def _bharat_run_wkhtmltopdf_subprocess(command_args, bodies, header, footer):
    """Convert prepared HTML to PDF via wkhtmltopdf (no ORM — safe in thread pool)."""
    files_command_args = []
    temporary_files = []

    if header:
        head_file_fd, head_file_path = tempfile.mkstemp(suffix='.html', prefix='report.header.tmp.')
        with closing(os.fdopen(head_file_fd, 'wb')) as head_file:
            head_file.write(header.encode())
        temporary_files.append(head_file_path)
        files_command_args.extend(['--header-html', head_file_path])
    if footer:
        foot_file_fd, foot_file_path = tempfile.mkstemp(suffix='.html', prefix='report.footer.tmp.')
        with closing(os.fdopen(foot_file_fd, 'wb')) as foot_file:
            foot_file.write(footer.encode())
        temporary_files.append(foot_file_path)
        files_command_args.extend(['--footer-html', foot_file_path])

    paths = []
    for i, body in enumerate(bodies):
        prefix = '%s%d.' % ('report.body.tmp.', i)
        body_file_fd, body_file_path = tempfile.mkstemp(suffix='.html', prefix=prefix)
        with closing(os.fdopen(body_file_fd, 'wb')) as body_file:
            if len(body) < 4 * 1024 * 1024:
                body_file.write(body.encode())
            else:
                tree = lxml.html.fromstring(body)
                _split_table(tree, 500)
                body_file.write(lxml.html.tostring(tree))
        paths.append(body_file_path)
        temporary_files.append(body_file_path)

    pdf_report_fd, pdf_report_path = tempfile.mkstemp(suffix='.pdf', prefix='report.tmp.')
    os.close(pdf_report_fd)
    temporary_files.append(pdf_report_path)

    try:
        wkhtmltopdf = (
            [_get_wkhtmltopdf_bin()]
            + list(command_args)
            + files_command_args
            + paths
            + [pdf_report_path]
        )
        process = subprocess.Popen(
            wkhtmltopdf,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
        )
        _out, err = process.communicate()

        if process.returncode not in (0, 1):
            if process.returncode == -11:
                message = _(
                    'Wkhtmltopdf failed (error code: %(error_code)s). Memory limit too low or '
                    'maximum file number of subprocess reached. Message : %(message)s',
                    error_code=process.returncode,
                    message=err[-1000:],
                )
            else:
                message = _(
                    'Wkhtmltopdf failed (error code: %(error_code)s). Message: %(message)s',
                    error_code=process.returncode,
                    message=err[-1000:],
                )
            _logger.warning(message)
            raise UserError(message)
        if err:
            _logger.warning('wkhtmltopdf: %s', err)

        with open(pdf_report_path, 'rb') as pdf_document:
            pdf_content = pdf_document.read()
    finally:
        for temporary_file in temporary_files:
            try:
                os.unlink(temporary_file)
            except OSError:
                _logger.error('Error when trying to remove file %s', temporary_file)

    return pdf_content


def _raise_file_descriptor_limit(min_limit=4096):
    """Best-effort raise of soft RLIMIT_NOFILE before bulk wkhtmltopdf runs."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(max(min_limit, soft), hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except (ValueError, OSError):
        pass


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _bharat_icp_get(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _bharat_pdf_parallel_workers(self):
        return read_parallel_workers(self._bharat_icp_get)

    @api.model
    def _bharat_pdf_merge_chunk(self):
        return read_merge_chunk(self._bharat_icp_get)

    @api.model
    def _bharat_pdf_fast_mode(self):
        return read_fast_mode(self._bharat_icp_get)

    @api.model
    def bharat_qr_to_data_uri(self, payload, width=96, height=96):
        """Build an inline QR image for QWeb/PDF (SVG avoids reportlab renderPM/Pillow)."""
        payload = (payload or '').strip()
        if not payload:
            return False

        w, h = int(width), int(height)
        try:
            from reportlab.graphics.barcode import createBarcodeDrawing

            drawing = createBarcodeDrawing(
                'QR',
                value=payload,
                format='svg',
                width=w,
                height=h,
                barBorder=2,
            )
            svg_data = drawing.asString('svg')
            if isinstance(svg_data, str):
                svg_data = svg_data.encode('utf-8')
            encoded = base64.b64encode(svg_data).decode('ascii')
            return 'data:image/svg+xml;base64,%s' % encoded
        except Exception:
            _logger.debug('bharatnyay_core: SVG QR failed, trying PNG barcode()', exc_info=True)

        try:
            png_bytes = self.barcode(
                'QR',
                payload,
                width=w,
                height=h,
                barBorder=2,
                quiet=False,
            )
            return 'data:image/png;base64,%s' % base64.b64encode(png_bytes).decode('ascii')
        except Exception:
            _logger.warning(
                'bharatnyay_core: could not render QR (install reportlab renderPM or use SVG path)',
            )
            return False

    def _is_bharatnyay_pdf_report(self, report_ref=False):
        report = self._get_report(report_ref) if report_ref else self
        name = (report.report_name or report.report_file or '') if report else ''
        return name.startswith('bharatnyay_core.')

    def _normalize_res_ids(self, res_ids):
        if not res_ids:
            return []
        if isinstance(res_ids, int):
            return [res_ids]
        return list(res_ids)

    def _bharat_wkhtmltopdf_user_error(self, err):
        """Turn wkhtmltopdf resource failures into actionable guidance."""
        msg = (err.args[0] if err.args else '') or ''
        low = msg.lower()
        if 'wkhtmltopdf failed' not in low:
            return None
        if any(token in low for token in (
            'error code: -6',
            'error code: -11',
            'too many open files',
            'memory limit',
            'maximum file number',
            'thread pipe',
        )):
            return UserError(
                _('PDF generation failed: wkhtmltopdf ran out of memory or file handles.\n\n'
                  'Bulk prints use parallel workers; if this persists:\n'
                  '1. Lower System Parameter bharat.pdf.parallel_workers (e.g. 3)\n'
                  '2. Restart Odoo and run: pkill -f wkhtmltopdf\n'
                  '3. Start Odoo with: ulimit -n 65536')
            )
        return None

    def _prepare_single_loan_pdf(self, report_ref, res_id, data=None):
        """QWeb HTML + wkhtmltopdf args for one loan (must run on main ORM thread)."""
        additional_context = {'debug': False, 'bharat_light_pdf': True}
        payload = dict(data or {})
        payload.setdefault('debug', False)
        report_sudo = self._get_report(report_ref)
        report_ctx = self.with_context(**additional_context)

        html = report_ctx._render_qweb_html(report_ref, [res_id], data=payload)[0]
        bodies, _html_ids, header, footer, specific_paperformat_args = report_sudo.with_context(
            **additional_context,
        )._prepare_html(html, report_model=report_sudo.model)

        command_args = report_ctx._build_wkhtmltopdf_args(
            report_sudo.get_paperformat(),
            self.env.context.get('landscape'),
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=self.env.context.get('set_viewport_size'),
        )
        return {
            'res_id': res_id,
            'command_args': command_args,
            'bodies': bodies,
            'header': header,
            'footer': footer,
        }

    def _render_loan_pdf_streams_ordered(self, report_ref, res_ids, data=None):
        """Render per-loan PDFs; QWeb sequential, wkhtmltopdf parallel when batch > 1."""
        workers = self._bharat_pdf_parallel_workers()
        prepared = []
        for res_id in res_ids:
            try:
                prepared.append(self._prepare_single_loan_pdf(report_ref, res_id, data=data))
            except UserError as err:
                friendly = self._bharat_wkhtmltopdf_user_error(err)
                if friendly:
                    raise friendly from err
                raise

        def _run_one(pkg):
            return pkg['res_id'], _bharat_run_wkhtmltopdf_subprocess(
                pkg['command_args'],
                pkg['bodies'],
                pkg['header'],
                pkg['footer'],
            )

        if workers <= 1 or len(prepared) <= 1:
            results = {}
            for pkg in prepared:
                res_id, pdf_bytes = _run_one(pkg)
                results[res_id] = pdf_bytes
            return [io.BytesIO(results[res_id]) for res_id in res_ids]

        _raise_file_descriptor_limit(max(4096, workers * 32))
        results = {}
        max_workers = min(workers, len(prepared))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_run_one, pkg) for pkg in prepared]
            for fut in as_completed(futures):
                res_id, pdf_bytes = fut.result()
                results[res_id] = pdf_bytes

        elapsed = time.time() - t0
        _logger.info(
            'bharatnyay_core: parallel wkhtmltopdf for %s case(s) in %.1fs (%s workers)',
            len(res_ids), elapsed, max_workers,
        )
        return [io.BytesIO(results[res_id]) for res_id in res_ids]

    def _render_bharat_qweb_pdf_merged(self, report_ref, res_ids, data=None):
        """One wkhtmltopdf job per loan (parallel), then merge into one PDF."""
        report = self._get_report(report_ref)
        merge_chunk = self._bharat_pdf_merge_chunk()
        partial_streams = []
        t0 = time.time()

        for chunk_ids in split_every(merge_chunk, res_ids):
            loan_streams = self._render_loan_pdf_streams_ordered(
                report_ref, chunk_ids, data=data,
            )
            if len(loan_streams) == 1:
                partial_streams.append(loan_streams[0])
            else:
                partial_streams.append(self._merge_pdfs(loan_streams))

        if len(partial_streams) == 1:
            pdf_content = partial_streams[0].getvalue()
        else:
            pdf_content = self._merge_pdfs(partial_streams).getvalue()

        _logger.info(
            'bharatnyay_core: merged PDF for %s (%s record(s), report %s) in %.1fs (workers=%s)',
            report.model, len(res_ids), report.report_name, time.time() - t0,
            self._bharat_pdf_parallel_workers(),
        )
        return pdf_content, 'pdf'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        if self._is_bharatnyay_pdf_report(report_ref):
            _raise_file_descriptor_limit()
            ids = self._normalize_res_ids(res_ids)
            if len(ids) > 1:
                try:
                    return self._render_bharat_qweb_pdf_merged(report_ref, ids, data=data)
                except UserError as err:
                    friendly = self._bharat_wkhtmltopdf_user_error(err)
                    if friendly:
                        raise friendly from err
                    raise
            try:
                return super(
                    IrActionsReport,
                    self.with_context(bharat_light_pdf=True),
                )._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
            except UserError as err:
                friendly = self._bharat_wkhtmltopdf_user_error(err)
                if friendly:
                    raise friendly from err
                raise
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    @api.model
    def _build_wkhtmltopdf_args(
            self,
            paperformat_id,
            landscape,
            specific_paperformat_args=None,
            set_viewport_size=False):
        command_args = super()._build_wkhtmltopdf_args(
            paperformat_id,
            landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )
        if not self.env.context.get('bharat_light_pdf'):
            return command_args

        filtered = []
        skip_next = False
        for arg in command_args:
            if skip_next:
                skip_next = False
                continue
            if arg in ('--javascript-delay', '--header-line'):
                skip_next = True
                continue
            filtered.append(arg)

        filtered.extend([
            '--disable-javascript',
            '--no-stop-slow-scripts',
            '--load-error-handling', 'ignore',
            '--load-media-error-handling', 'ignore',
        ])
        if self._bharat_pdf_fast_mode():
            filtered.extend([
                '--lowquality',
                '--image-quality', '60',
            ])
        else:
            filtered.extend([
                '--image-quality', '75',
            ])
        filtered = [a for a in filtered if a != '--disable-smart-shrinking']
        return filtered
>>>>>>> Stashed changes
