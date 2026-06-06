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
