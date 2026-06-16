# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BharatProcessRun(models.Model):
    _name = 'bharat.process.run'
    _description = 'BharatNyay background process run'
    _order = 'started_at desc, id desc'

    name = fields.Char(required=True, index=True)
    job_code = fields.Selection(
        [
            ('milestone_scheduler', 'Workflow auto-advance'),
            ('milestone_advance', 'Milestone advance'),
            ('case_vault_build', 'Case Vault build'),
            ('portfolio_import', 'Portfolio import'),
            ('pod_import', 'POD status import'),
        ],
        string='Job type',
        required=True,
        index=True,
    )
    state = fields.Selection(
        [
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('done', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Stopped'),
        ],
        default='queued',
        required=True,
        index=True,
    )
    batch_number = fields.Char(string='Batch', index=True)
    user_id = fields.Many2one('res.users', string='Started by', default=lambda self: self.env.user)
    started_at = fields.Datetime(string='Started', default=fields.Datetime.now, index=True)
    finished_at = fields.Datetime(string='Finished')
    duration_seconds = fields.Float(string='Duration (s)', digits=(12, 2))
    progress_current = fields.Integer(string='Progress')
    progress_total = fields.Integer(string='Total steps')
    message = fields.Text(string='Summary')
    error_message = fields.Text(string='Error')
    cancel_requested = fields.Boolean(string='Stop requested', default=False, index=True)

    @api.model
    def start(self, job_code, name, batch_number=False):
        return self.create({
            'job_code': job_code,
            'name': name,
            'batch_number': (batch_number or '').strip() or False,
            'state': 'running',
            'started_at': fields.Datetime.now(),
            'cancel_requested': False,
        })

    def mark_running(self):
        self.write({
            'state': 'running',
            'started_at': fields.Datetime.now(),
            'finished_at': False,
            'error_message': False,
            'cancel_requested': False,
        })

    def update_progress(self, current, total, message=False):
        vals = {
            'progress_current': current,
            'progress_total': total,
        }
        if message:
            vals['message'] = message
        self.write(vals)

    def finish(self, message=''):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == 'cancelled':
                continue
            started = rec.started_at or now
            duration = max(0.0, (now - started).total_seconds())
            rec.write({
                'state': 'done',
                'finished_at': now,
                'duration_seconds': round(duration, 2),
                'message': message or rec.message,
                'error_message': False,
                'cancel_requested': False,
            })

    def fail(self, error_message=''):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == 'cancelled':
                continue
            started = rec.started_at or now
            duration = max(0.0, (now - started).total_seconds())
            rec.write({
                'state': 'failed',
                'finished_at': now,
                'duration_seconds': round(duration, 2),
                'error_message': error_message or _('Unknown error'),
            })

    def _do_cancel(self, reason=''):
        """Mark job stopped (kill switch)."""
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ('done', 'failed', 'cancelled'):
                continue
            started = rec.started_at or now
            duration = max(0.0, (now - started).total_seconds())
            rec.write({
                'cancel_requested': True,
                'state': 'cancelled',
                'finished_at': now,
                'duration_seconds': round(duration, 2),
                'message': reason or _('Stopped.'),
                'error_message': False,
            })

    def action_cancel(self):
        """Stop queued or running jobs."""
        Vault = self.env['bharat.case.vault.batch']
        to_stop = self.filtered(lambda r: r.state in ('queued', 'running'))
        if not to_stop:
            raise UserError(_('Nothing to stop — job is not queued or running.'))
        reason = _('Stopped by %s.') % self.env.user.name
        for rec in to_stop:
            rec._do_cancel(reason)
            if rec.job_code == 'case_vault_build' and rec.batch_number:
                vault = Vault.search([('batch_number', '=', rec.batch_number)], limit=1)
                if vault and vault.vault_state in ('queued', 'building'):
                    vault.write({
                        'vault_state': 'cancelled',
                        'build_message': reason,
                    })
        Vault._disable_vault_queue()
        return True

    @api.model
    def action_cancel_all_active(self):
        """Kill switch — stop every queued/running background job."""
        active = self.search([('state', 'in', ('queued', 'running'))])
        if active:
            active.action_cancel()
        else:
            self.env['bharat.case.vault.batch']._disable_vault_queue()
        return True

    def action_rerun(self):
        """Re-queue a Case Vault build for the batch."""
        Vault = self.env['bharat.case.vault.batch']
        for rec in self:
            if rec.job_code != 'case_vault_build' or not rec.batch_number:
                raise UserError(_('Only Case Vault batch jobs can be rerun here.'))
            vault = Vault.ensure_for_batch(rec.batch_number)
            if vault.vault_state in ('queued', 'building'):
                raise UserError(
                    _('Batch %(batch)s is already queued or building.')
                    % {'batch': rec.batch_number}
                )
            vault.action_queue_build()
        return True

    def action_delete_process_runs(self):
        """Delete selected job history rows (admin cleanup)."""
        if not self:
            raise UserError(_('Select at least one background job to delete.'))
        self._check_process_run_delete_allowed()
        count = len(self)
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Background jobs'),
                'message': _('Removed %(n)s job record(s).') % {'n': count},
                'type': 'success',
                'sticky': False,
            },
        }

    def _check_process_run_delete_allowed(self):
        if not self.env.user.has_group('bharatnyay_core.group_bharat_admin') and not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only BharatNyay admins can delete background job records.'))
        active = self.filtered(lambda r: r.state in ('queued', 'running'))
        if active:
            raise UserError(
                _('Stop active jobs before deleting them: %s')
                % ', '.join(active.mapped('name'))
            )

    def unlink(self):
        self._check_process_run_delete_allowed()
        Vault = self.env['bharat.case.vault.batch']
        for rec in self:
            vaults = Vault.search([('process_run_id', '=', rec.id)])
            if vaults:
                vaults.write({'process_run_id': False})
        return super().unlink()

    def is_cancelled(self):
        self.ensure_one()
        if self.cancel_requested or self.state == 'cancelled':
            return True
        fresh = self.browse(self.id)
        return bool(fresh.cancel_requested or fresh.state == 'cancelled')

    @api.model
    def log_milestone_advance(self, case_count, batches_queued=None):
        """Record a milestone-advance action and any vault rebuilds it queued."""
        batches_queued = batches_queued or []
        run = self.create({
            'job_code': 'milestone_advance',
            'name': _('Milestone advance — %(n)s case(s)') % {'n': case_count},
            'state': 'running',
            'started_at': fields.Datetime.now(),
        })
        parts = [_('Advanced %(n)s case(s).') % {'n': case_count}]
        if batches_queued:
            parts.append(
                _('Case Vault rebuild queued: %s') % ', '.join(batches_queued)
            )
        run.finish('\n'.join(parts))
        return run

    @api.model
    def dashboard_snapshot(self, page=1, page_size=5):
        """JSON payload for OWL dashboards (paginated job history)."""
        Vault = self.env['bharat.case.vault.batch']
        Loan = self.env['bharat.loan']
        running = self.search([('state', 'in', ('queued', 'running'))])
        page = max(1, int(page or 1))
        page_size = min(max(1, int(page_size or 5)), 20)
        total_count = self.search_count([])
        state_groups = self.read_group([], ['state'], ['state'])
        state_counts = {g['state']: g['state_count'] for g in state_groups}
        success_count = state_counts.get('done', 0)
        failed_count = state_counts.get('failed', 0)
        running_only = state_counts.get('running', 0)
        queued_count = state_counts.get('queued', 0)
        active_count = running_only + queued_count
        stopped_count = state_counts.get('cancelled', 0)
        offset = (page - 1) * page_size
        recent = self.search([], order='started_at desc, id desc', limit=page_size, offset=offset)
        last_scheduler = self.search([
            ('job_code', '=', 'milestone_scheduler'),
            ('state', 'in', ('done', 'failed', 'cancelled')),
        ], order='finished_at desc, id desc', limit=1)

        job_type_labels = dict(self._fields['job_code'].selection)

        def _serialize(run):
            case_count = 0
            if run.batch_number:
                case_count = Loan.search_count([('batch_number', '=', run.batch_number)])

            return {
                'id': run.id,
                'name': run.name,
                'job_code': run.job_code,
                'job_type_label': job_type_labels.get(run.job_code, run.job_code),
                'state': run.state,
                'state_label': dict(self._fields['state'].selection).get(run.state, run.state),
                'batch_number': run.batch_number or False,
                'case_count': case_count,
                'started_at': fields.Datetime.to_string(run.started_at) if run.started_at else False,
                'finished_at': fields.Datetime.to_string(run.finished_at) if run.finished_at else False,
                'duration_seconds': run.duration_seconds or 0.0,
                'progress_current': run.progress_current or 0,
                'progress_total': run.progress_total or 0,
                'message': run.message or '',
                'error_message': run.error_message or '',
                'can_cancel': run.state in ('queued', 'running'),
                'can_rerun': (
                    run.job_code == 'case_vault_build'
                    and bool(run.batch_number)
                    and run.state in ('done', 'failed', 'cancelled')
                ),
            }

        total_pages = max(1, (total_count + page_size - 1) // page_size)

        payload = {
            'running_count': active_count,
            'running_only_count': running_only,
            'queued_count': queued_count,
            'success_count': success_count,
            'failed_count': failed_count,
            'stopped_count': stopped_count,
            'summary': {
                'total': total_count,
                'active': active_count,
                'running': running_only,
                'queued': queued_count,
                'success': success_count,
                'failed': failed_count,
                'stopped': stopped_count,
            },
            'running': [_serialize(r) for r in running],
            'recent': [_serialize(r) for r in recent],
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'last_scheduler': _serialize(last_scheduler) if last_scheduler else False,
            'queue_enabled': Vault._vault_queue_enabled(),
            'has_active_jobs': bool(running),
        }
        return payload

    def action_open_case_vault(self):
        self.ensure_one()
        if not self.batch_number:
            return False
        vault = self.env['bharat.case.vault.batch'].search(
            [('batch_number', '=', self.batch_number)], limit=1,
        )
        if vault:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Case Vault'),
                'res_model': 'bharat.case.vault.batch',
                'view_mode': 'list,form',
                'domain': [('id', '=', vault.id)],
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Case Vault'),
            'res_model': 'bharat.case.vault.batch',
            'view_mode': 'list,form',
            'domain': [('batch_number', '=', self.batch_number)],
            'target': 'current',
        }
