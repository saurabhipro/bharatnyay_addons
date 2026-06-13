/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatMonetary } from "@web/views/fields/formatters";
import {
    pieGradient,
    dashboardFilterFields,
    dashboardFilterRpcArgs,
    loadDashboardFilterOptions,
    mergeLoanDomain,
    onDashboardFilterRegionChange,
    onDashboardFilterStateChange,
    onDashboardFilterBatchChange,
    batchVolumeRows,
    batchBarHeight as batchBarHeightHelper,
    batchSegPctCount as batchSegPctCountHelper,
    openRoleInvoices,
    openPodStatusRecords,
} from "./dashboard_helpers";

function defaultDateRange() {
    const to = new Date();
    const from = new Date();
    from.setMonth(from.getMonth() - 3);
    return {
        date_to: to.toISOString().slice(0, 10),
        date_from: from.toISOString().slice(0, 10),
    };
}

export class CaseManagerDashboard extends Component {
    static template = "bharatnyay_core.CaseManagerDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const dr = defaultDateRange();
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            date_from: dr.date_from,
            date_to: dr.date_to,
            pieStyle: pieGradient([]),
            branchPieStyle: pieGradient([]),
            locationPieStyle: pieGradient([]),
            workflowPieStyle: pieGradient([]),
            paymentPieStyle: pieGradient([]),
            batchVolumeMode: "payment",
            ...dashboardFilterFields(),
        });
        onWillStart(async () => {
            await loadDashboardFilterOptions(this.orm, this.state, "case_manager");
            await this.load();
        });
    }

    _applyPieStyles(data) {
        this.state.pieStyle = pieGradient(data.product_mix || []);
        this.state.branchPieStyle = pieGradient(data.branch_mix || []);
        this.state.locationPieStyle = pieGradient(data.location_mix || []);
        this.state.workflowPieStyle = pieGradient(data.workflow_mix || []);
        this.state.paymentPieStyle = pieGradient(data.payment_mix || []);
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "bharat.loan",
                "get_case_manager_dashboard_statistics",
                [],
                {
                    date_from: this.state.date_from || false,
                    date_to: this.state.date_to || false,
                    ...dashboardFilterRpcArgs(this.state),
                }
            );
            this.state.data = data;
            this._applyPieStyles(data);
        } catch (e) {
            this.state.data = null;
            this.state.error = e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefresh() {
        await loadDashboardFilterOptions(this.orm, this.state, "case_manager");
        await this.load();
    }

    async onFilterRegionChange(ev) {
        await onDashboardFilterRegionChange(
            this.orm, this.state, ev, "case_manager", () => this.load()
        );
    }

    async onFilterStateChange(ev) {
        await onDashboardFilterStateChange(
            this.orm, this.state, ev, "case_manager", () => this.load()
        );
    }

    async onFilterBatchChange(ev) {
        await onDashboardFilterBatchChange(this.orm, this.state, ev, () => this.load());
    }

    onDateFrom(ev) {
        this.state.date_from = ev.target.value;
    }

    onDateTo(ev) {
        this.state.date_to = ev.target.value;
    }

    async applyDateFilter() {
        await this.load();
    }

    hearingDtLabel(iso) {
        if (!iso) {
            return "";
        }
        const d = new Date(iso.replace(" ", "T") + "Z");
        return d.toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    openMyCases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "My cases",
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
        const domain = await this.orm.call("bharat.loan", "get_progress_bucket_domain", [
            stage,
            this.state.data?.loan_domain || [],
        ]);
        const match = (this.state.data?.stage_cards || []).find((s) => s.key === stage);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: match?.label || stage,
            res_model: "bharat.loan",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    openMixCases(ev) {
        const kind = ev.currentTarget?.dataset?.mixKind;
        const rawId = ev.currentTarget?.dataset?.mixId;
        if (!kind || rawId === undefined || rawId === null || rawId === "") {
            return;
        }
        const recordId = parseInt(rawId, 10);
        const field = kind === "branch" ? "branch_id" : "location_id";
        const domain = mergeLoanDomain(this.state, [
            recordId > 0 ? [field, "=", recordId] : [field, "=", false],
        ]);
        const title = kind === "branch" ? "Cases by branch" : "Cases by location";
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "bharat.loan",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
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
            views: [[false, "list"], [false, "form"]],
            domain: mergeLoanDomain(this.state, batchDomain),
            target: "current",
        });
    }

    openUnbilledCases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pending billing",
            res_model: "bharat.loan.billing.event",
            views: [[false, "list"]],
            domain: this.state.data?.pending_billing_domain || [["state", "=", "pending"]],
            target: "current",
        });
    }

    openPendingPostalStatus() {
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

    openPodStatusCases(ev) {
        const key = ev.currentTarget?.dataset?.podKey;
        if (!key) {
            return;
        }
        const card = (this.state.data?.pod_status_cards || []).find((c) => c.key === key);
        if (!card) {
            return;
        }
        openPodStatusRecords(this.action, card);
    }

    openInvoices(ev) {
        const mode = ev.currentTarget?.dataset?.filter || "all";
        openRoleInvoices(this.action, this.state, mode);
    }

    openLoan(ev) {
        const id = parseInt(ev.currentTarget?.dataset?.loanId, 10);
        if (!id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Case",
            res_model: "bharat.loan",
            views: [[false, "form"]],
            res_id: id,
            target: "current",
        });
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
}

registry.category("actions").add("bharatnyay_case_manager_dashboard", CaseManagerDashboard);
