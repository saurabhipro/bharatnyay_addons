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

    def is_cancelled(self):
        self.ensure_one()
        if self.cancel_requested or self.state == 'cancelled':
            return True
        fresh = self.browse(self.id)
        return bool(fresh.cancel_requested or fresh.state == 'cancelled')

    @api.model
    def dashboard_snapshot(self):
        """JSON payload for OWL dashboards."""
        Vault = self.env['bharat.case.vault.batch']
        running = self.search([('state', 'in', ('queued', 'running'))])
        recent = self.search([], order='started_at desc, id desc', limit=8)
        last_scheduler = self.search([
            ('job_code', '=', 'milestone_scheduler'),
            ('state', 'in', ('done', 'failed', 'cancelled')),
        ], order='finished_at desc, id desc', limit=1)

        def _serialize(run):
            return {
                'id': run.id,
                'name': run.name,
                'job_code': run.job_code,
                'state': run.state,
                'batch_number': run.batch_number or False,
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

        payload = {
            'running_count': len(running),
            'running': [_serialize(r) for r in running],
            'recent': [_serialize(r) for r in recent],
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
