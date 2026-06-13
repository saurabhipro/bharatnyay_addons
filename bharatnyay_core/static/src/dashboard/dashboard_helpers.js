/** @odoo-module **/

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
    return action.doAction("bharatnyay_core.action_bharat_loan", {
        name: name || "Cases",
        domain: domain || [],
        view_mode: "list,form",
    });
}

/** POD dashboard tiles → notices, interim orders, or awards (not cases). */
export function openPodStatusRecords(action, card) {
    const open = card?.open;
    if (!open?.res_model) {
        return Promise.resolve();
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

export function openRoleInvoices(action, state, mode = "all") {
    const domains = state.data?.invoice_domains || {};
    const domain = domains[mode] || domains.all || [["id", "=", 0]];
    const titles = {
        all: "Invoices (my cases)",
        paid: "Paid invoices (my cases)",
        unpaid: "Unpaid invoices (my cases)",
        draft: "Draft invoices (my cases)",
    };
    action.doAction({
        type: "ir.actions.act_window",
        name: titles[mode] || titles.all,
        res_model: "account.move",
        views: [[false, "list"], [false, "form"]],
        domain,
        context: { default_move_type: "out_invoice" },
        target: "current",
    });
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
