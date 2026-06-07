# -*- coding: utf-8 -*-
import base64
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VAULT_DOCUMENT_SPECS = (
    ('notice_1', 'Notice 1', 'bharatnyay_core.action_report_bharat_loan_notice'),
    (
        'interim_order_1', 'Interim Order 1',
        'bharatnyay_core.action_report_bharat_loan_hearing_proceedings',
    ),
    ('award', 'Award', 'bharatnyay_core.action_report_bharat_loan_award_letter'),
)


class BharatCaseVaultBatch(models.Model):
    _name = 'bharat.case.vault.batch'
    _description = 'Case Vault — batch notice PDF archive'
    _order = 'last_built_at desc, batch_number desc, id desc'

    batch_number = fields.Char(string='Batch', required=True, index=True)
    case_count = fields.Integer(string='Cases in batch', readonly=True)
    vault_state = fields.Selection(
        [
            ('empty', 'Not built'),
            ('queued', 'Queued'),
            ('building', 'Building'),
            ('ready', 'Ready'),
            ('failed', 'Failed'),
        ],
        string='Vault status',
        default='empty',
        required=True,
        index=True,
    )
    last_built_at = fields.Datetime(string='Last built', readonly=True)
    build_message = fields.Text(string='Build log', readonly=True)
    process_run_id = fields.Many2one(
        'bharat.process.run',
        string='Last process run',
        readonly=True,
        ondelete='set null',
    )

    notice_1_pdf = fields.Binary(string='Notice 1 PDF', attachment=True)
    notice_1_pdf_filename = fields.Char(string='Notice 1 filename')
    notice_1_case_count = fields.Integer(string='Notice 1 pages', readonly=True)

    interim_order_1_pdf = fields.Binary(string='Interim Order 1 PDF', attachment=True)
    interim_order_1_pdf_filename = fields.Char(string='Interim Order 1 filename')
    interim_order_1_case_count = fields.Integer(string='Interim Order 1 pages', readonly=True)

    award_pdf = fields.Binary(string='Award PDF', attachment=True)
    award_pdf_filename = fields.Char(string='Award filename')
    award_case_count = fields.Integer(string='Award pages', readonly=True)

    _sql_constraints = [
        (
            'batch_number_unique',
            'unique(batch_number)',
            'Each batch can only have one Case Vault record.',
        ),
    ]

    @staticmethod
    def _safe_batch_slug(batch_number):
        text = (batch_number or 'batch').strip()
        slug = re.sub(r'[^\w\-]+', '_', text, flags=re.UNICODE)
        return slug.strip('_') or 'batch'

    @api.model
    def ensure_for_batch(self, batch_number):
        bn = (batch_number or '').strip()
        if not bn:
            return self.browse()
        vault = self.search([('batch_number', '=', bn)], limit=1)
        if vault:
            return vault
        case_count = self.env['bharat.loan'].search_count([('batch_number', '=', bn)])
        return self.create({
            'batch_number': bn,
            'case_count': case_count,
            'vault_state': 'empty',
        })

    @api.model
    def action_sync_batches_from_cases(self):
        batches = {
            (bn or '').strip()
            for bn in self.env['bharat.loan'].search([]).mapped('batch_number')
            if (bn or '').strip()
        }
        created = 0
        for bn in sorted(batches):
            if not self.search([('batch_number', '=', bn)], limit=1):
                self.ensure_for_batch(bn)
                created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Case Vault'),
                'message': _('Synced %(n)s new batch vault record(s).') % {'n': created},
                'type': 'success',
                'sticky': False,
            },
        }

    def _loan_ids_for_batch(self):
        self.ensure_one()
        loans = self.env['bharat.loan'].search([('batch_number', '=', self.batch_number)])
        return loans.ids

    def _render_merged_pdf(self, loan_ids, report_xmlid):
        if not loan_ids:
            return False
        report = self.env.ref(report_xmlid, raise_if_not_found=False)
        if not report:
            raise UserError(_('Report %s is not installed.') % report_xmlid)
        pdf_bytes, report_type = report._render_qweb_pdf(report, res_ids=loan_ids)
        if report_type != 'pdf':
            raise UserError(_('Expected PDF output from report %s.') % report_xmlid)
        return pdf_bytes

    def _download_action(self, field_name, default_filename):
        self.ensure_one()
        if not getattr(self, field_name):
            raise UserError(_('PDF not available yet. Build or rebuild the Case Vault first.'))
        filename = getattr(self, field_name.replace('_pdf', '_pdf_filename')) or default_filename
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content/?model=%s&id=%s&field=%s&filename=%s&download=true'
            ) % (self._name, self.id, field_name, filename),
            'target': 'self',
        }

    def action_download_notice_1(self):
        return self._download_action('notice_1_pdf', 'Notice_1.pdf')

    def action_download_interim_order_1(self):
        return self._download_action('interim_order_1_pdf', 'Interim_Order_1.pdf')

    def action_download_award(self):
        return self._download_action('award_pdf', 'Award.pdf')

    def action_queue_build(self):
        for rec in self:
            if rec.vault_state in ('queued', 'building'):
                continue
            run = self.env['bharat.process.run'].create({
                'job_code': 'case_vault_build',
                'name': _('Case Vault — %s') % rec.batch_number,
                'batch_number': rec.batch_number,
                'state': 'queued',
            })
            rec.write({
                'vault_state': 'queued',
                'process_run_id': run.id,
                'build_message': _('Queued for background build.'),
            })
        cron = self.env.ref(
            'bharatnyay_core.ir_cron_bharat_case_vault_builder',
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()
        return True

    def action_rebuild_now(self):
        """Build synchronously (for small batches / manual retry)."""
        self.ensure_one()
        self._execute_build(async_mode=False)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Case Vault'),
                'message': self.build_message or _('Build finished.'),
                'type': 'success' if self.vault_state == 'ready' else 'warning',
                'sticky': True,
            },
        }

    def _execute_build(self, async_mode=True):
        self.ensure_one()
        loan_ids = self._loan_ids_for_batch()
        self.case_count = len(loan_ids)
        if not loan_ids:
            self.write({
                'vault_state': 'failed',
                'build_message': _('No cases found for batch %s.') % self.batch_number,
            })
            if self.process_run_id:
                self.process_run_id.fail(_('No cases in batch.'))
            return False

        run = self.process_run_id
        if not run:
            run = self.env['bharat.process.run'].start(
                'case_vault_build',
                _('Case Vault — %s') % self.batch_number,
                self.batch_number,
            )
            self.process_run_id = run.id
        else:
            run.mark_running()

        self.write({
            'vault_state': 'building',
            'build_message': _('Rendering PDFs for %(n)s case(s)…') % {'n': len(loan_ids)},
        })

        slug = self._safe_batch_slug(self.batch_number)
        vals = {'last_built_at': fields.Datetime.now()}
        log_lines = []
        total_steps = len(VAULT_DOCUMENT_SPECS)

        try:
            for step, (field_key, label, xmlid) in enumerate(VAULT_DOCUMENT_SPECS, start=1):
                run.update_progress(
                    step,
                    total_steps,
                    _('Building %(doc)s (%(step)s/%(total)s)…') % {
                        'doc': label.replace('_', ' ').title(),
                        'step': step,
                        'total': total_steps,
                    },
                )
                pdf_bytes = self._render_merged_pdf(loan_ids, xmlid)
                if not pdf_bytes:
                    log_lines.append(_('%s: skipped (empty).') % label)
                    continue
                filename = '%s_%s.pdf' % (label, slug)
                vals.update({
                    '%s_pdf' % field_key: base64.b64encode(pdf_bytes),
                    '%s_pdf_filename' % field_key: filename,
                    '%s_case_count' % field_key: len(loan_ids),
                })
                log_lines.append(
                    _('%s: %(n)s case(s), %(size)s KB.') % {
                        'label': label,
                        'n': len(loan_ids),
                        'size': round(len(pdf_bytes) / 1024, 1),
                    }
                )

            vals.update({
                'vault_state': 'ready',
                'build_message': '\n'.join(log_lines),
            })
            self.write(vals)
            summary = _('Case Vault ready — %(batch)s (%(n)s cases).') % {
                'batch': self.batch_number,
                'n': self.case_count,
            }
            run.finish(summary)
            _logger.info('Case Vault built for %s (%s cases)', self.batch_number, self.case_count)
            return True
        except Exception as exc:
            _logger.exception('Case Vault build failed for %s', self.batch_number)
            self.write({
                'vault_state': 'failed',
                'build_message': (self.build_message or '') + '\n' + str(exc),
            })
            run.fail(str(exc))
            if not async_mode:
                raise
            return False

    @api.model
    def _cron_process_vault_queue(self):
        """Background worker: build one queued vault at a time."""
        if self.search_count([('vault_state', '=', 'building')]):
            return False
        vault = self.search([('vault_state', '=', 'queued')], order='write_date asc, id asc', limit=1)
        if not vault:
            return False
        vault._execute_build(async_mode=True)
        if self.search_count([('vault_state', '=', 'queued')]):
            cron = self.env.ref(
                'bharatnyay_core.ir_cron_bharat_case_vault_builder',
                raise_if_not_found=False,
            )
            if cron:
                cron._trigger()
        return True

    @api.model
    def queue_build_for_batch(self, batch_number):
        bn = (batch_number or '').strip()
        if not bn:
            return self.browse()
        vault = self.ensure_for_batch(bn)
        vault.action_queue_build()
        return vault
