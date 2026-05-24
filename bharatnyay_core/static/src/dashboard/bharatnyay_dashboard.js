/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatMonetary } from "@web/views/fields/formatters";

const LINE_W = 800;
const LINE_H = 180;
const PAD = 28;

function computeLineChart(series) {
    const empty = {
        lineW: LINE_W,
        lineH: LINE_H,
        linePoints1: "",
        linePoints2: "",
        areaPoints1: "",
        areaPoints2: "",
        lineDots1: [],
        lineDots2: [],
    };
    if (!series.length) {
        return empty;
    }
    const innerW = LINE_W - PAD * 2;
    const innerH = LINE_H - PAD * 2;
    const counts = series.map((s) => s.count || 0);
    const claims = series.map((s) => s.claim_sum || 0);
    const maxC = Math.max(...counts, 1);
    const maxCl = Math.max(...claims, 1);
    const n = series.length;
    const step = innerW / Math.max(n - 1, 1);
    const baselineY = PAD + innerH;

    const ptsCount = counts.map((c, i) => {
        const x = PAD + i * step;
        const y = PAD + innerH * (1 - c / maxC);
        return { x, y, str: `${x},${y}` };
    });
    const ptsClaim = claims.map((cl, i) => {
        const x = PAD + i * step;
        const y = PAD + innerH * (1 - cl / maxCl);
        return { x, y, str: `${x},${y}` };
    });

    const linePoints1 = ptsCount.map((p) => p.str).join(" ");
    const linePoints2 = ptsClaim.map((p) => p.str).join(" ");
    const areaPoints1 = `${PAD},${baselineY} ${linePoints1} ${PAD + innerW},${baselineY}`;
    const areaPoints2 = `${PAD},${baselineY} ${linePoints2} ${PAD + innerW},${baselineY}`;
    return {
        lineW: LINE_W,
        lineH: LINE_H,
        linePoints1,
        linePoints2,
        areaPoints1,
        areaPoints2,
        lineDots1: ptsCount,
        lineDots2: ptsClaim,
    };
}

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
            chart: computeLineChart([]),
            pieStyle: pieGradient([]),
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
            this.state.chart = computeLineChart(data.monthly_created || []);
            this.state.pieStyle = pieGradient(data.product_mix || []);
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
            domain: [["state_code", "=", stage]],
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

    barHeight(count) {
        const s = this.state.data?.monthly_created || [];
        const max = Math.max(...s.map((m) => m.count || 0), 1);
        return Math.round(((count || 0) / max) * 100);
    }

    shortMonth(period) {
        if (!period) {
            return "";
        }
        const [y, mo] = period.split("-");
        const names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const mi = parseInt(mo, 10);
        const yy = y && String(y).length >= 4 ? String(y).slice(2) : mo;
        return `${names[mi] || mo}'${yy}`;
    }
}

registry.category("actions").add("bharatnyay_dashboard", BharatnyayDashboard);
