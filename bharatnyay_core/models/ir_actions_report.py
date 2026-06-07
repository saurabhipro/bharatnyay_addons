# -*- coding: utf-8 -*-
import base64
import io
import logging
import resource
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.modules.registry import Registry
from odoo.tools import split_every

from ..tools.pdf_render import read_fast_mode, read_merge_chunk, read_parallel_workers

_logger = logging.getLogger(__name__)


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

    def _render_one_loan_pdf_thread(self, report_ref, res_id, uid, ctx, data):
        """Render a single record PDF in its own DB cursor (thread-safe)."""
        dbname = self.env.cr.dbname
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, uid, ctx)
            report_model = env['ir.actions.report']
            try:
                pdf_bytes, report_type = super(
                    IrActionsReport, report_model,
                )._render_qweb_pdf(report_ref, res_ids=[res_id], data=data)
            except UserError as err:
                friendly = report_model._bharat_wkhtmltopdf_user_error(err)
                if friendly:
                    raise friendly from err
                raise
            if report_type != 'pdf':
                raise UserError(_('Expected PDF output from report %s') % report_ref)
            return res_id, pdf_bytes

    def _render_loan_pdf_streams_ordered(self, report_ref, res_ids, data=None):
        """Render per-loan PDFs; parallelize wkhtmltopdf when batch size > 1."""
        workers = self._bharat_pdf_parallel_workers()
        ctx = dict(self.env.context or {}, bharat_light_pdf=True)
        uid = self.env.uid

        if workers <= 1 or len(res_ids) <= 1:
            streams = []
            for res_id in res_ids:
                _rid, pdf_bytes = self._render_one_loan_pdf_thread(
                    report_ref, res_id, uid, ctx, data,
                )
                streams.append(io.BytesIO(pdf_bytes))
            return streams

        _raise_file_descriptor_limit(max(4096, workers * 32))
        results = {}
        max_workers = min(workers, len(res_ids))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(
                    self._render_one_loan_pdf_thread,
                    report_ref,
                    res_id,
                    uid,
                    ctx,
                    data,
                )
                for res_id in res_ids
            ]
            for fut in as_completed(futures):
                res_id, pdf_bytes = fut.result()
                results[res_id] = pdf_bytes

        elapsed = time.time() - t0
        _logger.info(
            'bharatnyay_core: parallel PDF rendered %s case(s) in %.1fs (%s workers)',
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
