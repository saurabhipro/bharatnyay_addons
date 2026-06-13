/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

/** Return false when the tile is empty and an info notice was shown. */
export function guardEmptyDashboardCard(
    notification,
    { count, label, amount, invoiceCount } = {}
) {
    const n = Number(count ?? 0);
    const hasAmount = amount !== undefined && amount !== null;
    const hasInvoices = invoiceCount !== undefined && invoiceCount !== null;
    const empty =
        n === 0 &&
        (!hasAmount || Number(amount || 0) === 0) &&
        (!hasInvoices || Number(invoiceCount || 0) === 0);
    if (!empty) {
        return true;
    }
    notification.add(_t("No data in this section."), {
        title: label || _t("This section"),
        type: "info",
    });
    return false;
}

export function guardEmptyInvoiceCard(notification, state, mode, label) {
    const kpis = state.data?.kpis || {};
    if (mode === "paid") {
        return guardEmptyDashboardCard(notification, {
            label: label || _t("Paid invoices"),
            amount: kpis.paid_invoice_amount,
            invoiceCount: kpis.paid_invoices,
        });
    }
    if (mode === "unpaid") {
        return guardEmptyDashboardCard(notification, {
            label: label || _t("Unpaid invoices"),
            amount: kpis.unpaid_invoice_amount,
            invoiceCount: kpis.unpaid_invoices,
        });
    }
    if (mode === "draft") {
        return guardEmptyDashboardCard(notification, {
            label: label || _t("Draft invoices"),
            count: kpis.draft_invoices,
        });
    }
    if (mode === "all") {
        return guardEmptyDashboardCard(notification, {
            label: label || _t("Total invoices"),
            count: kpis.total_invoices,
        });
    }
    return true;
}

export function pieGradient(mix) {
    if (!mix?.length) {
        return "conic-gradient(#e2e8f0 0% 100%)";
    }
    let acc = 0;
    const parts = [];
    for (const s of mix) {
        const start = acc;
        acc += s.percent;
        parts.push(`${s.color} ${start}% ${acc}%`);
    }
    return `conic-gradient(${parts.join(", ")})`;
}

/** Read Spiffy-derived palette CSS variables from the dashboard root. */
export function readDashboardThemePalette(rootEl, count = 8) {
    const el = rootEl || document.querySelector(".o_bharatnyay_dashboard");
    if (!el) {
        return null;
    }
    const style = getComputedStyle(el);
    const palette = [];
    for (let i = 1; i <= count; i++) {
        const color = style.getPropertyValue(`--bn-palette-${i}`).trim();
        if (color) {
            palette.push(color);
        }
    }
    if (!palette.length) {
        const accent = style.getPropertyValue("--bn-accent").trim();
        if (accent) {
            palette.push(accent);
        }
    }
    return palette.length ? palette : null;
}

export function applyThemePaletteToMix(mix, palette) {
    if (!mix?.length || !palette?.length) {
        return mix || [];
    }
    return mix.map((item, i) => ({
        ...item,
        color: palette[i % palette.length],
    }));
}

export function applyDashboardPieStyles(state, data, rootEl) {
    const palette = readDashboardThemePalette(rootEl);
    state.pieStyle = pieGradient(applyThemePaletteToMix(data.product_mix || [], palette));
    state.branchPieStyle = pieGradient(applyThemePaletteToMix(data.branch_mix || [], palette));
    state.locationPieStyle = pieGradient(applyThemePaletteToMix(data.location_mix || [], palette));
    state.workflowPieStyle = pieGradient(applyThemePaletteToMix(data.workflow_mix || [], palette));
    state.paymentPieStyle = pieGradient(applyThemePaletteToMix(data.payment_mix || [], palette));
}

export function dashboardFilterFields() {
    return {
        filter_region: "",
        filter_state: "",
        filter_batch: "",
        filter_options: { regions: [], states: [], batches: [] },
    };
}

export function dashboardFilterRpcArgs(state) {
    return {
        region_id: state.filter_region || false,
        state_id: state.filter_state || false,
        batch_number: state.filter_batch || false,
    };
}

export function mergeLoanDomain(state, extra = []) {
    const base = state.data?.loan_domain || [];
    return [...base, ...extra];
}

/** Open the configured loan list/form action (uses Cases list view with column widths). */
export function openLoanCases(action, { name, domain }) {
    // Use an explicit act_window — the XML action has a URL path that ignores domain overrides.
    return action.doAction({
        type: "ir.actions.act_window",
        name: name || "Cases",
        res_model: "bharat.loan",
        views: [[false, "list"], [false, "form"]],
        domain: domain || [],
        target: "current",
    });
}

/** Open cases for a pipeline stage tile — same records as the card count. */
export async function openStageBucketCases(
    orm,
    action,
    state,
    stage,
    stageCards,
    notification
) {
    const match = (stageCards || []).find((s) => s.key === stage);
    if (
        !guardEmptyDashboardCard(notification, {
            count: match?.count,
            label: match?.label || stage,
        })
    ) {
        return false;
    }
    let domain = match?.open_domain;
    if (!domain?.length && match?.loan_ids) {
        domain = [["id", "in", match.loan_ids.length ? match.loan_ids : [0]]];
    }
    if (!domain?.length) {
        domain = await orm.call("bharat.loan", "get_progress_bucket_domain", [
            stage,
            state.data?.loan_domain || [],
        ]);
    }
    await openLoanCases(action, {
        name: match?.label || stage,
        domain,
    });
    return true;
}

/** POD dashboard tiles → notices, interim orders, or awards (not cases). */
export function openPodStatusRecords(action, card, notification) {
    if (
        !guardEmptyDashboardCard(notification, {
            count: card?.count,
            label: card ? `${card.label} — ${card.status_label}` : _t("POD"),
        })
    ) {
        return Promise.resolve(false);
    }
    const open = card?.open;
    if (!open?.res_model) {
        return Promise.resolve(false);
    }
    return action.doAction({
        type: "ir.actions.act_window",
        name: open.name || `${card.label} — ${card.status_label}`,
        res_model: open.res_model,
        views: [[false, "list"], [false, "form"]],
        domain: open.domain || [],
        target: "current",
    });
}

/** Open pending billing events for one pipeline stage (or total). */
export function openUnbilledChargesStage(action, notification, state, stageKey) {
    const pipeline = state.data?.unbilled_charges_pipeline;
    if (!pipeline) {
        return Promise.resolve(false);
    }
    let card;
    let name;
    if (stageKey === "total") {
        card = pipeline.total;
        name = _t("Notice 1 / Hearing 1 / Award — unbilled");
    } else {
        card = (pipeline.stages || []).find((s) => s.key === stageKey);
        name = card?.label || _t("Unbilled charges");
    }
    if (
        !guardEmptyDashboardCard(notification, {
            count: card?.count,
            label: name,
            amount: card?.amount,
        })
    ) {
        return Promise.resolve(false);
    }
    return action.doAction({
        type: "ir.actions.act_window",
        name,
        res_model: "bharat.loan.billing.event",
        views: [[false, "list"], [false, "form"]],
        domain: card.domain || [["state", "=", "pending"]],
        target: "current",
    });
}

export async function loadDashboardFilterOptions(orm, state, dashboardRole = false) {
    state.filter_options = await orm.call(
        "bharat.loan",
        "get_dashboard_filter_options",
        [],
        {
            region_id: state.filter_region || false,
            state_id: state.filter_state || false,
            dashboard_role: dashboardRole || false,
        }
    );
}

function _resetInvalidDashboardFilters(state) {
    if (state.filter_state) {
        const stateOk = (state.filter_options.states || []).some(
            (s) => String(s.id) === String(state.filter_state)
        );
        if (!stateOk) {
            state.filter_state = "";
        }
    }
    if (state.filter_batch) {
        const batchOk = (state.filter_options.batches || []).some(
            (b) => String(b.key) === String(state.filter_batch)
        );
        if (!batchOk) {
            state.filter_batch = "";
        }
    }
}

export async function onDashboardFilterRegionChange(orm, state, ev, dashboardRole, reloadFn) {
    state.filter_region = ev.target.value;
    await loadDashboardFilterOptions(orm, state, dashboardRole);
    _resetInvalidDashboardFilters(state);
    await reloadFn();
}

export async function onDashboardFilterStateChange(orm, state, ev, dashboardRole, reloadFn) {
    state.filter_state = ev.target.value;
    await loadDashboardFilterOptions(orm, state, dashboardRole);
    _resetInvalidDashboardFilters(state);
    await reloadFn();
}

export async function onDashboardFilterBatchChange(orm, state, ev, reloadFn) {
    state.filter_batch = ev.target.value;
    await reloadFn();
}

export function openRoleInvoices(action, state, mode = "all", notification) {
    const titles = {
        all: _t("Invoices (my cases)"),
        paid: _t("Paid invoices (my cases)"),
        unpaid: _t("Unpaid invoices (my cases)"),
        draft: _t("Draft invoices (my cases)"),
    };
    if (notification && !guardEmptyInvoiceCard(notification, state, mode, titles[mode])) {
        return false;
    }
    const domains = state.data?.invoice_domains || {};
    const domain = domains[mode] || domains.all || [["id", "=", 0]];
    action.doAction({
        type: "ir.actions.act_window",
        name: titles[mode] || titles.all,
        res_model: "account.move",
        views: [[false, "list"], [false, "form"]],
        domain,
        context: { default_move_type: "out_invoice" },
        target: "current",
    });
    return true;
}

export function batchVolumeRows(state) {
    if (state.batchVolumeMode === "stage") {
        return state.data?.batch_volume_stages || [];
    }
    return state.data?.batch_volume || [];
}

export function batchBarHeight(state, count) {
    const rows = batchVolumeRows(state);
    const max = Math.max(...rows.map((b) => b.count || 0), 1);
    return Math.round(((count || 0) / max) * 100);
}

export function batchSegPctCount(batch, segCount) {
    const total = batch?.count || 0;
    if (!total) {
        return 0;
    }
    return Math.round(((segCount || 0) / total) * 100);
}
