# -*- coding: utf-8 -*-
import base64
import io
import logging
import resource

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import split_every

_logger = logging.getLogger(__name__)

# Render one loan per wkhtmltopdf run, then merge — avoids one huge HTML/PDF job.
_BHARAT_PDF_MERGE_CHUNK = 25


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
                  'Bulk prints are rendered one case at a time and merged; if this persists:\n'
                  '1. Restart Odoo and run: pkill -f wkhtmltopdf\n'
                  '2. Start Odoo with: ulimit -n 65536\n'
                  '3. Print fewer loans per batch from the list')
            )
        return None

    def _render_bharat_qweb_pdf_merged(self, report_ref, res_ids, data=None):
        """One wkhtmltopdf job per loan, then append pages into a single PDF."""
        report = self._get_report(report_ref)
        ctx_report = self.with_context(bharat_light_pdf=True)
        partial_streams = []

        for chunk_ids in split_every(_BHARAT_PDF_MERGE_CHUNK, res_ids):
            loan_streams = []
            for res_id in chunk_ids:
                try:
                    pdf_bytes, report_type = super(
                        IrActionsReport, ctx_report,
                    )._render_qweb_pdf(report_ref, res_ids=[res_id], data=data)
                except UserError as err:
                    friendly = self._bharat_wkhtmltopdf_user_error(err)
                    if friendly:
                        raise friendly from err
                    raise
                if report_type != 'pdf':
                    return pdf_bytes, report_type
                loan_streams.append(io.BytesIO(pdf_bytes))

            if len(loan_streams) == 1:
                partial_streams.append(loan_streams[0])
            else:
                partial_streams.append(self._merge_pdfs(loan_streams))

        if len(partial_streams) == 1:
            pdf_content = partial_streams[0].getvalue()
        else:
            pdf_content = self._merge_pdfs(partial_streams).getvalue()

        _logger.info(
            'bharatnyay_core: merged PDF for %s (%s record(s), report %s)',
            report.model, len(res_ids), report.report_name,
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

        # Drop heavy defaults; keep PDF generation within RAM on typical VPS setups.
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
            '--load-error-handling', 'ignore',
            '--load-media-error-handling', 'ignore',
            '--image-quality', '75',
        ])
        # Allow wkhtmltopdf to shrink content so each notice letter stays on one page.
        filtered = [a for a in filtered if a != '--disable-smart-shrinking']
        return filtered
