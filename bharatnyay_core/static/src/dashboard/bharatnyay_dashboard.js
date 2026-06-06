/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatMonetary } from "@web/views/fields/formatters";

function pieGradient(productMix) {
    if (!productMix?.length) {
        return "conic-gradient(#e2e8f0 0% 100%)";
    }
    let acc = 0;
    const parts = [];
    for (const s of productMix) {
        const start = acc;
        acc += s.percent;
        parts.push(`${s.color} ${start}% ${acc}%`);
    }
    return `conic-gradient(${parts.join(", ")})`;
}

export class BharatnyayDashboard extends Component {
    static template = "bharatnyay_core.BharatnyayDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

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
        });

        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("bharat.loan", "get_dashboard_statistics", []);
            this.state.data = data;
            this.state.pieStyle = pieGradient(data.product_mix || []);
            this.state.branchPieStyle = pieGradient(data.branch_mix || []);
            this.state.locationPieStyle = pieGradient(data.location_mix || []);
            this.state.workflowPieStyle = pieGradient(data.workflow_mix || []);
            this.state.paymentPieStyle = pieGradient(data.payment_mix || []);
        } catch (e) {
            this.state.data = null;
            this.state.error = e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefresh() {
        await this.load();
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
            [["loan_number", "=", q]],
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
            domain: [["loan_number", "ilike", q]],
            target: "current",
        });
    }

    openLoanList() {
        this.action.doAction("bharatnyay_core.action_bharat_loan");
    }

    openStageCases(ev) {
        const stage = ev.currentTarget?.dataset?.stage;
        if (!stage) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Loan stage",
            res_model: "bharat.loan",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["milestone_code", "=", stage]],
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
        const domain =
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
            domain,
            target: "current",
        });
    }

    openInvoices(ev) {
        const mode = ev.currentTarget?.dataset?.filter || "all";
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

    openBatchCases(ev) {
        const batchKey = ev.currentTarget?.dataset?.batch;
        if (batchKey === undefined || batchKey === null || batchKey === "__other__") {
            return;
        }
        const domain =
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
            domain,
            target: "current",
        });
    }
}

registry.category("actions").add("bharatnyay_dashboard", BharatnyayDashboard);
