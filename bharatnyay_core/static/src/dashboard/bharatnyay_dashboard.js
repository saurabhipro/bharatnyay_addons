/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatDateTime, formatMonetary } from "@web/views/fields/formatters";
import { deserializeDateTime } from "@web/core/l10n/dates";
import {
    applyDashboardPieStyles,
    pieGradient,
    dashboardFilterFields,
    dashboardFilterRpcArgs,
    loadDashboardFilterOptions,
    mergeLoanDomain,
    restoreDashboardBatchFilter,
    openLoanCases,
    openPodStatusRecords,
    openStageBucketCases,
    openUnbilledChargesStage,
    openConsolidatedBillingWizard,
    guardEmptyDashboardCard,
    guardEmptyInvoiceCard,
    onDashboardFilterRegionChange,
    onDashboardFilterStateChange,
    onDashboardFilterBatchChange,
    batchVolumeRows,
    batchBarHeight as batchBarHeightHelper,
    batchSegPctCount as batchSegPctCountHelper,
    isPipelineLinkStage as isPipelineLinkStageHelper,
    podGroupForStage as podGroupForStageHelper,
    chargeStageForKey as chargeStageForKeyHelper,
    pipelineLinkedStages as pipelineLinkedStagesHelper,
} from "./dashboard_helpers";

export class BharatnyayDashboard extends Component {
    static template = "bharatnyay_core.BharatnyayDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");

        this.state = useState({
            loading: true,
            error: null,
            data: null,
            pieStyle: pieGradient([]),
            branchPieStyle: pieGradient([]),
            locationPieStyle: pieGradient([]),
            workflowPieStyle: pieGradient([]),
            paymentPieStyle: pieGradient([]),
            search: "",
            jobsPage: 1,
            jobsPageSize: 5,
            batchVolumeMode: "payment",
            ...dashboardFilterFields(),
        });

        onWillStart(async () => {
            await loadDashboardFilterOptions(this.orm, this.state);
            await restoreDashboardBatchFilter(this.orm, this.state);
            await this.load();
        });

        this._processPollTimer = null;
        onWillUnmount(() => {
            if (this._processPollTimer) {
                clearInterval(this._processPollTimer);
            }
        });
    }

    async load(silent = false) {
        if (!silent) {
            this.state.loading = true;
        }
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "bharat.loan",
                "get_dashboard_statistics",
                [],
                {
                    ...dashboardFilterRpcArgs(this.state),
                    jobs_page: this.state.jobsPage,
                    jobs_page_size: this.state.jobsPageSize,
                }
            );
            this.state.data = data;
            applyDashboardPieStyles(this.state, data, document.querySelector(".o_bharatnyay_dashboard"));
            this._scheduleProcessPoll();
        } catch (e) {
            this.state.data = null;
            this.state.error = e?.message || String(e);
        } finally {
            if (!silent) {
                this.state.loading = false;
            }
        }
    }

    async onRefresh() {
        await loadDashboardFilterOptions(this.orm, this.state);
        await this.load();
    }

    async onFilterRegionChange(ev) {
        await onDashboardFilterRegionChange(this.orm, this.state, ev, false, () => this.load());
    }

    async onFilterStateChange(ev) {
        await onDashboardFilterStateChange(this.orm, this.state, ev, false, () => this.load());
    }

    async onFilterBatchChange(ev) {
        await onDashboardFilterBatchChange(this.orm, this.state, ev, () => this.load());
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        this.onSearchSubmit();
    }

    async onSearchSubmit() {
        const q = this.state.search.trim();
        if (!q) {
            return;
        }
        const exact = await this.orm.searchRead(
            "bharat.loan",
            mergeLoanDomain(this.state, [["loan_number", "=", q]]),
            ["id"],
            { limit: 1 }
        );
        if (exact.length) {
            this.action.doAction({
                type: "ir.actions.act_window",
                name: "Loan",
                res_model: "bharat.loan",
                views: [[false, "form"]],
                res_id: exact[0].id,
                target: "current",
            });
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Loan sheet",
            res_model: "bharat.loan",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: mergeLoanDomain(this.state, [["loan_number", "ilike", q]]),
            target: "current",
        });
    }

    openLoanList() {
        if (
            !guardEmptyDashboardCard(this.notification, {
                count: this.state.data?.kpis?.total_loans,
                label: "Total cases",
            })
        ) {
            return;
        }
        this._openLoanListAction();
    }

    openTotalBatches() {
        if (
            !guardEmptyDashboardCard(this.notification, {
                count: this.state.data?.kpis?.total_batches,
                label: "Total batches",
            })
        ) {
            return;
        }
        this._openLoanListAction();
    }

    openImportBatch() {
        this.action.doAction("bharatnyay_core.action_bharat_loan_portfolio_import_wizard", {
            onClose: () => this.load(),
        });
    }

    openCaseManagers() {
        this.action.doAction("bharatnyay_core.action_bharat_case_managers");
    }

    openNewCaseManager() {
        this.action.doAction("bharatnyay_core.action_bharat_new_case_manager", {
            onClose: () => this.load(),
        });
    }

    openArbitrators() {
        this.action.doAction("bharatnyay_core.action_bharat_arbitrators");
    }

    openNewArbitrator() {
        this.action.doAction("bharatnyay_core.action_bharat_new_arbitrator", {
            onClose: () => this.load(),
        });
    }

    moveCasesToNextStage() {
        const count = this.state.data?.kpis?.movable_cases || 0;
        if (!count) {
            this.notification.add("No cases in the current filter can be advanced.", {
                type: "warning",
            });
            return;
        }
        this.action.doAction("bharatnyay_core.action_bharat_loan_milestone_advance_wizard", {
            additionalContext: {
                dashboard_region_id: this.state.filter_region || false,
                dashboard_state_id: this.state.filter_state || false,
                dashboard_batch_number: this.state.filter_batch || false,
            },
            onClose: () => {
                if (this._processPollTimer) {
                    clearInterval(this._processPollTimer);
                }
                this._processPollTimer = setInterval(() => this.load(true), 5000);
                void this.load(true);
                this._scheduleProcessPoll();
            },
        });
    }

    markPodDelivered() {
        const count = this.state.data?.kpis?.pod_markable_count || 0;
        if (!count) {
            this.notification.add("No pending POD delivery rows in the current filter.", {
                type: "warning",
            });
            return;
        }
        this.action.doAction("bharatnyay_core.action_bharat_loan_pod_mark_done_wizard", {
            additionalContext: {
                dashboard_region_id: this.state.filter_region || false,
                dashboard_state_id: this.state.filter_state || false,
                dashboard_batch_number: this.state.filter_batch || false,
            },
            onClose: () => {
                void this.load(true);
            },
        });
    }

    runFlowSimulation() {
        if (!this.state.data?.kpis?.simulation_available) {
            this.notification.add(
                "No unlocked demo case in the current filter. Import a batch or widen filters.",
                { type: "warning" },
            );
            return;
        }
        this.action.doAction("bharatnyay_core.action_bharat_flow_simulation", {
            additionalContext: {
                dashboard_region_id: this.state.filter_region || false,
                dashboard_state_id: this.state.filter_state || false,
                dashboard_batch_number: this.state.filter_batch || false,
            },
            onClose: () => {
                void this.load(true);
            },
        });
    }

    openRunningJobs() {
        if (!this.processActiveCount()) {
            this.notification.add("No background jobs are running or queued.", {
                type: "info",
            });
            return;
        }
        this.openProcessRunsActive();
    }

    _openLoanListAction() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Loan sheet",
            res_model: "bharat.loan",
            views: [[false, "list"], [false, "form"]],
            domain: this.state.data?.loan_domain || [],
            target: "current",
        });
    }

    async openStageCases(ev) {
        const stage = ev.currentTarget?.dataset?.stage;
        if (!stage) {
            return;
        }
        await openStageBucketCases(
            this.orm,
            this.action,
            this.state,
            stage,
            this.state.data?.stage_cards || [],
            this.notification,
        );
    }

    isPipelineLinkStage(stageKey) {
        return isPipelineLinkStageHelper(stageKey);
    }

    podGroupForStage(stageKey) {
        return podGroupForStageHelper(this.state.data, stageKey);
    }

    chargeStageForKey(stageKey) {
        return chargeStageForKeyHelper(this.state.data, stageKey);
    }

    pipelineLinkedStages() {
        return pipelineLinkedStagesHelper(this.state.data);
    }

    openPodStatusCases(ev) {
        const key = ev.currentTarget?.dataset?.podKey;
        if (!key) {
            return;
        }
        const card = (this.state.data?.pod_status_cards || []).find((c) => c.key === key);
        if (!card) {
            return;
        }
        openPodStatusRecords(this.action, card, this.notification);
    }

    openMixCases(ev) {
        const kind = ev.currentTarget?.dataset?.mixKind;
        const rawId = ev.currentTarget?.dataset?.mixId;
        if (!kind || rawId === undefined || rawId === null || rawId === "") {
            return;
        }
        const recordId = parseInt(rawId, 10);
        const field = kind === "branch" ? "branch_id" : "location_id";
        const extra =
            recordId > 0
                ? [[field, "=", recordId]]
                : [[field, "=", false]];
        const title = kind === "branch" ? "Cases by branch" : "Cases by location";
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "bharat.loan",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: mergeLoanDomain(this.state, extra),
            target: "current",
        });
    }

    openUnbilledCases() {
        openUnbilledChargesStage(
            this.action,
            this.notification,
            this.state,
            "total",
        );
    }

    openUnbilledChargesStage(ev) {
        const key = ev.currentTarget?.dataset?.chargeKey;
        if (!key) {
            return;
        }
        openUnbilledChargesStage(
            this.action,
            this.notification,
            this.state,
            key,
        );
    }

    openConsolidatedBillingFromStage(ev) {
        const key = ev.currentTarget?.dataset?.chargeKey;
        if (!key) {
            return;
        }
        openConsolidatedBillingWizard(
            this.action,
            this.notification,
            this.state,
            key,
        );
    }

    openPendingPostalStatus() {
        if (
            !guardEmptyDashboardCard(this.notification, {
                count: this.state.data?.kpis?.postal_status_pending_count,
                label: "Awaiting POD status",
            })
        ) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Awaiting POD status",
            res_model: "bharat.loan.postal.dispatch",
            views: [[false, "list"], [false, "form"]],
            domain: this.state.data?.postal_pending_status_domain || [],
            context: { create: false },
            target: "current",
        });
    }

    openBillBatchWizard() {
        this.orm
            .call("bharat.loan", "bharat_consolidated_billing_wizard_action", [], {
                batch_number: this.state.filter_batch || false,
            })
            .then((action) => this.action.doAction(action));
    }

    openInvoices(ev) {
        const mode = ev.currentTarget?.dataset?.filter || "all";
        const titles = {
            all: "Total invoices",
            paid: "Invoices paid",
            unpaid: "Invoices unpaid",
            draft: "Draft invoices",
        };
        if (!guardEmptyInvoiceCard(this.notification, this.state, mode, titles[mode])) {
            return;
        }
        const domain = [
            ["move_type", "=", "out_invoice"],
            ["bharat_arbitration_invoice", "=", true],
        ];
        if (mode === "draft") {
            domain.push(["state", "=", "draft"]);
        } else if (mode === "paid") {
            domain.push(["state", "=", "posted"]);
            domain.push(["payment_state", "in", ["paid", "in_payment"]]);
        } else if (mode === "unpaid") {
            domain.push(["state", "=", "posted"]);
            domain.push(["payment_state", "not in", ["paid", "in_payment"]]);
            domain.push(["amount_residual", ">", 0]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Arbitration invoices",
            res_model: "account.move",
            views: [[false, "list"], [false, "form"]],
            domain,
            context: { default_move_type: "out_invoice" },
            target: "current",
        });
    }

    _scheduleProcessPoll() {
        if (this._processPollTimer) {
            clearInterval(this._processPollTimer);
            this._processPollTimer = null;
        }
        const running = this.processActiveCount();
        const vaultBuilding = this.state.data?.case_vault?.building_count || 0;
        if (running > 0 || vaultBuilding > 0) {
            this._processPollTimer = setInterval(() => this.load(true), 15000);
        }
    }

    openProcessRuns(domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Background jobs",
            res_model: "bharat.process.run",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    openProcessRunsActive() {
        this.openProcessRuns([["state", "in", ["queued", "running"]]]);
    }

    openProcessRunsFiltered(state) {
        this.openProcessRuns([["state", "=", state]]);
    }

    openCaseVault() {
        this.action.doAction("bharatnyay_core.action_bharat_case_vault_batch");
    }

    async cancelJob(ev, jobId) {
        ev?.stopPropagation?.();
        ev?.preventDefault?.();
        if (!jobId) {
            return;
        }
        await this.orm.call("bharat.process.run", "action_cancel", [[jobId]]);
        await this.load(true);
    }

    async rerunJob(ev, jobId) {
        ev?.stopPropagation?.();
        ev?.preventDefault?.();
        if (!jobId) {
            return;
        }
        await this.orm.call("bharat.process.run", "action_rerun", [[jobId]]);
        await this.load(true);
    }

    async cancelAllJobs() {
        await this.orm.call("bharat.process.run", "action_cancel_all_active", []);
        await this.load(true);
    }

    fmtDuration(seconds) {
        const s = Number(seconds) || 0;
        if (s < 60) {
            return `${s.toFixed(s < 10 ? 1 : 0)}s`;
        }
        const mins = Math.floor(s / 60);
        const rem = Math.round(s % 60);
        return rem ? `${mins}m ${rem}s` : `${mins}m`;
    }

    processStateLabel(state) {
        const labels = {
            done: "Completed",
            failed: "Failed",
            running: "Running",
            queued: "Queued",
            cancelled: "Stopped",
        };
        return labels[state] || state;
    }

    processStateIcon(state) {
        const icons = {
            done: "fa-check-circle",
            failed: "fa-exclamation-circle",
            running: "fa-spinner fa-spin",
            queued: "fa-clock-o",
            cancelled: "fa-stop-circle",
        };
        return icons[state] || "fa-circle-o";
    }

    processActiveCount() {
        const processes = this.state.data?.processes;
        if (!processes) {
            return 0;
        }
        return (processes.summary && processes.summary.active) || processes.running_count || 0;
    }

    processProgressLabel(job) {
        if (job.progress_total > 0) {
            return `${job.progress_current}/${job.progress_total}`;
        }
        return job.state === "running" ? "In progress" : "Queued";
    }

    fmtDateTime(value) {
        if (!value) {
            return "—";
        }
        try {
            return formatDateTime(deserializeDateTime(value));
        } catch {
            return value;
        }
    }

    processJobsTotalPages() {
        return this.state.data?.processes?.total_pages || 1;
    }

    processJobsTotalCount() {
        return this.state.data?.processes?.total_count || 0;
    }

    processJobsPageLabel() {
        const page = this.state.data?.processes?.page || this.state.jobsPage;
        return `${page} / ${this.processJobsTotalPages()}`;
    }

    async processJobsPrev() {
        if (this.state.jobsPage <= 1) {
            return;
        }
        this.state.jobsPage -= 1;
        await this.load(true);
    }

    async processJobsNext() {
        if (this.state.jobsPage >= this.processJobsTotalPages()) {
            return;
        }
        this.state.jobsPage += 1;
        await this.load(true);
    }

    openVaultRecord(vaultId) {
        if (!vaultId) {
            this.openCaseVault();
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Case Vault",
            res_model: "bharat.case.vault.batch",
            views: [[false, "form"]],
            res_id: vaultId,
            target: "current",
        });
    }

    async queueVaultBuild(ev, vaultId) {
        ev?.stopPropagation?.();
        ev?.preventDefault?.();
        if (!vaultId) {
            return;
        }
        await this.orm.call("bharat.case.vault.batch", "action_queue_build", [[vaultId]]);
        await this.load(true);
    }

    async stopVaultBuild(ev, vaultId) {
        ev?.stopPropagation?.();
        ev?.preventDefault?.();
        if (!vaultId) {
            return;
        }
        await this.orm.call("bharat.case.vault.batch", "action_cancel_build", [[vaultId]]);
        await this.load(true);
    }

    downloadJobFile(ev, url) {
        ev?.preventDefault?.();
        ev?.stopPropagation?.();
        if (!url) {
            return;
        }
        window.open(url, "_blank");
    }

    fmtInt(n) {
        return new Intl.NumberFormat().format(n || 0);
    }

    fmtMoney(amount) {
        const d = this.state.data;
        if (!d?.currency_id) {
            return new Intl.NumberFormat(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }).format(amount || 0);
        }
        return formatMonetary(amount || 0, { currencyId: d.currency_id });
    }

    batchBarHeight(count) {
        return batchBarHeightHelper(this.state, count);
    }

    batchSegPct(batch, key) {
        const total = batch?.count || 0;
        if (!total) {
            return 0;
        }
        return Math.round(((batch[key] || 0) / total) * 100);
    }

    batchSegPctCount(batch, segCount) {
        return batchSegPctCountHelper(batch, segCount);
    }

    batchVolumeHasData() {
        return batchVolumeRows(this.state).length > 0;
    }

    onBatchVolumeModeChange(ev) {
        this.state.batchVolumeMode = ev.target.value === "stage" ? "stage" : "payment";
    }

    batchBarTitle(batch) {
        const paid = batch?.paid_cases || 0;
        const unpaid = batch?.unpaid_cases || 0;
        const other = batch?.other_cases || 0;
        return `${batch?.batch || ""} — ${this.fmtInt(batch?.count || 0)} cases · Paid ${this.fmtInt(paid)} · Unpaid ${this.fmtInt(unpaid)} · Other ${this.fmtInt(other)}`;
    }

    batchBarTitleStage(batch) {
        const parts = (batch?.segments || []).map(
            (seg) => `${seg.label} ${this.fmtInt(seg.count)}`
        );
        return `${batch?.batch || ""} — ${this.fmtInt(batch?.count || 0)} cases · ${parts.join(" · ")}`;
    }

    openBatchStageCases(ev) {
        ev?.stopPropagation?.();
        ev?.preventDefault?.();
        const slot = ev.currentTarget?.closest(".bn-bar-slot");
        const batchKey = slot?.dataset?.batch;
        const stage = ev.currentTarget?.dataset?.stage;
        if (!stage || batchKey === undefined || batchKey === null || batchKey === "__other__") {
            return;
        }
        const batchDomain =
            batchKey === ""
                ? [["batch_number", "in", [false, ""]]]
                : [["batch_number", "=", batchKey]];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Cases by batch and stage",
            res_model: "bharat.loan",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: mergeLoanDomain(this.state, [
                ...batchDomain,
                ["milestone_code", "=", stage],
            ]),
            target: "current",
        });
    }

    shortBatchLabel(batch) {
        if (!batch) {
            return "";
        }
        const label = String(batch);
        return label.length > 14 ? `${label.slice(0, 13)}…` : label;
    }

    openBatchCases(ev) {
        const batchKey = ev.currentTarget?.dataset?.batch;
        if (batchKey === undefined || batchKey === null || batchKey === "__other__") {
            return;
        }
        const batchDomain =
            batchKey === ""
                ? [["batch_number", "in", [false, ""]]]
                : [["batch_number", "=", batchKey]];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Cases by batch",
            res_model: "bharat.loan",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: mergeLoanDomain(this.state, batchDomain),
            target: "current",
        });
    }
}

registry.category("actions").add("bharatnyay_dashboard", BharatnyayDashboard);
