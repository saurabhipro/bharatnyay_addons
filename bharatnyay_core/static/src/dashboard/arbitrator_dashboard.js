/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatMonetary } from "@web/views/fields/formatters";

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
        const dr = defaultDateRange();
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            date_from: dr.date_from,
            date_to: dr.date_to,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "bharat.loan",
                "get_arbitrator_dashboard_statistics",
                [],
                {
                    date_from: this.state.date_from || false,
                    date_to: this.state.date_to || false,
                }
            );
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

    onDateFrom(ev) {
        this.state.date_from = ev.target.value;
    }

    onDateTo(ev) {
        this.state.date_to = ev.target.value;
    }

    async applyDateFilter() {
        await this.load();
    }

    percentLabel(percent) {
        return `${percent || 0}%`;
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

    async openBucket(ev) {
        const key = ev.currentTarget?.dataset?.bucket;
        if (!key) {
            return;
        }
        const base = this.state.data?.loan_domain || [];
        const domain = await this.orm.call(
            "bharat.loan",
            "get_progress_bucket_domain",
            [key, base]
        );
        const cards = this.state.data?.bucket_cards || [];
        const match = cards.find((b) => b.key === key);
        const label = match ? match.label : key;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: label,
            res_model: "bharat.loan",
            views: [[false, "list"], [false, "form"]],
            domain,
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

    openInvoices(ev) {
        const mode = ev.currentTarget?.dataset?.filter || "all";
        const domain = [
            ["move_type", "=", "out_invoice"],
            ["bharat_arbitration_invoice", "=", true],
        ];
        if (this.state.date_from) {
            domain.push(["invoice_date", ">=", this.state.date_from]);
        }
        if (this.state.date_to) {
            domain.push(["invoice_date", "<=", this.state.date_to]);
        }
        if (mode === "draft") {
            domain.push(["state", "=", "draft"]);
        } else if (mode === "paid") {
            domain.push(["state", "=", "posted"]);
            domain.push(["payment_state", "in", ["paid", "in_payment"]]);
        } else if (mode === "due") {
            domain.push(["state", "=", "posted"]);
            domain.push(["payment_state", "not in", ["paid", "in_payment"]]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Invoices (my cases)",
            res_model: "account.move",
            views: [[false, "list"], [false, "form"]],
            domain,
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
}

registry.category("actions").add("bharatnyay_arbitrator_dashboard", ArbitratorDashboard);
