/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatMonetary } from "@web/views/fields/formatters";
import {
    dashboardFilterFields,
    dashboardFilterRpcArgs,
    loadDashboardFilterOptions,
    mergeLoanDomain,
    onDashboardFilterRegionChange,
    onDashboardFilterStateChange,
    onDashboardFilterBatchChange,
    openRoleInvoices,
    openPodStatusRecords,
    openStageBucketCases,
    guardEmptyDashboardCard,
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

export class ArbitratorDashboard extends Component {
    static template = "bharatnyay_core.ArbitratorDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const dr = defaultDateRange();
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            date_from: dr.date_from,
            date_to: dr.date_to,
            ...dashboardFilterFields(),
        });
        onWillStart(async () => {
            await loadDashboardFilterOptions(this.orm, this.state, "arbitrator");
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "bharat.loan",
                "get_arbitrator_dashboard_statistics",
                [],
                {
                    date_from: this.state.date_from || false,
                    date_to: this.state.date_to || false,
                    ...dashboardFilterRpcArgs(this.state),
                }
            );
            this.state.data = data;
        } catch (e) {
            this.state.data = null;
            this.state.error = e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefresh() {
        await loadDashboardFilterOptions(this.orm, this.state, "arbitrator");
        await this.load();
    }

    async onFilterRegionChange(ev) {
        await onDashboardFilterRegionChange(
            this.orm, this.state, ev, "arbitrator", () => this.load()
        );
    }

    async onFilterStateChange(ev) {
        await onDashboardFilterStateChange(
            this.orm, this.state, ev, "arbitrator", () => this.load()
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
        if (
            !guardEmptyDashboardCard(this.notification, {
                count: this.state.data?.kpis?.total_cases,
                label: "My cases",
            })
        ) {
            return;
        }
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
        const cards =
            this.state.data?.hearing_stage_cards?.find((s) => s.key === stage)
                ? this.state.data?.hearing_stage_cards
                : this.state.data?.stage_cards;
        await openStageBucketCases(
            this.orm,
            this.action,
            this.state,
            stage,
            cards || [],
            this.notification,
        );
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

    openInvoices(ev) {
        const mode = ev.currentTarget?.dataset?.filter || "all";
        openRoleInvoices(this.action, this.state, mode, this.notification);
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
        const s = this.state.data?.batch_volume || [];
        const max = Math.max(...s.map((b) => b.count || 0), 1);
        return Math.round(((count || 0) / max) * 100);
    }

    shortBatchLabel(batch) {
        if (!batch) {
            return "";
        }
        const label = String(batch);
        return label.length > 14 ? `${label.slice(0, 13)}…` : label;
    }
}

registry.category("actions").add("bharatnyay_arbitrator_dashboard", ArbitratorDashboard);
