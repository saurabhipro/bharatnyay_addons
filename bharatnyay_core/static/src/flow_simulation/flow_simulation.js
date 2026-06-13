/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const INTERACTIVE_WIZARD_KEYS = new Set([
    "schedule_hearing",
    "interim_order",
    "final_award",
]);

function normalizeWindowAction(action) {
    if (!action || action.type !== "ir.actions.act_window") {
        return action;
    }
    if (action.views?.length) {
        return action;
    }
    const modes = (action.view_mode || "form")
        .split(",")
        .map((mode) => mode.trim())
        .filter(Boolean);
    return {
        ...action,
        views: (modes.length ? modes : ["form"]).map((mode) => [false, mode]),
    };
}

export class FlowSimulation extends Component {
    static template = "bharatnyay_core.FlowSimulation";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            error: null,
            payload: null,
            message: "",
            busy: false,
            waitingForUser: false,
            lastClientAction: null,
        });

        this._autoTimer = null;
        this._simulationId = null;

        onWillStart(async () => {
            await this._bootstrap();
        });

        onWillUnmount(() => {
            this._clearAutoTimer();
        });
    }

    _filterArgs() {
        const ctx = this.props.action?.context || {};
        return {
            region_id: ctx.dashboard_region_id || false,
            state_id: ctx.dashboard_state_id || false,
            batch_number: ctx.dashboard_batch_number || false,
        };
    }

    _clearAutoTimer() {
        if (this._autoTimer) {
            clearTimeout(this._autoTimer);
            this._autoTimer = null;
        }
    }

    _sleep(ms) {
        return new Promise((resolve) => {
            this._autoTimer = setTimeout(resolve, ms);
        });
    }

    async _bootstrap() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const payload = await this.orm.call(
                "bharat.loan.flow.simulation",
                "start_simulation",
                [],
                this._filterArgs(),
            );
            this._applyPayload(payload);
            await this._advance(false);
        } catch (e) {
            this.state.error = e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    _applyPayload(payload) {
        this.state.payload = payload;
        this._simulationId = payload?.simulation_id || null;
        if (payload?.message) {
            this.state.message = payload.message;
        }
    }

    async _advance(confirmed = false) {
        if (!this._simulationId || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.waitingForUser = false;
        this._clearAutoTimer();
        try {
            const payload = await this.orm.call(
                "bharat.loan.flow.simulation",
                "advance_simulation",
                [[this._simulationId]],
                { confirmed },
            );
            this._applyPayload(payload);
            if (payload.done) {
                this.state.message = payload.message || "Demo finished.";
                if (payload.invoice_action) {
                    this.state.lastClientAction = payload.invoice_action;
                }
                return;
            }
            if (payload.wait && payload.client_action) {
                this.state.waitingForUser = true;
                this.state.lastClientAction = payload.client_action;
                this.state.message =
                    payload.message ||
                    payload.current_step?.prompt ||
                    payload.current_step?.subtitle ||
                    this.state.message;
                this.state.busy = false;
                this._launchClientAction(payload.client_action);
                return;
            }
            if (payload.auto_continue) {
                this.state.busy = false;
                await this._sleep(payload.auto_pause_ms || 1400);
                await this._advance(false);
                return;
            }
        } catch (e) {
            this.state.error = e?.message || String(e);
            this.notification.add(this.state.error, { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    _launchClientAction(clientAction) {
        const action = normalizeWindowAction(clientAction);
        try {
            this.action.doAction(action);
        } catch (e) {
            this.notification.add(e?.message || String(e), { type: "danger" });
        }
    }

    async _openClientAction(clientAction) {
        this._launchClientAction(clientAction);
    }

    progressPct() {
        const p = this.state.payload;
        if (!p?.step_total) {
            return 0;
        }
        const idx = p.done ? p.step_total : Math.min(p.step_index + 1, p.step_total);
        return Math.round((idx / p.step_total) * 100);
    }

    progressLabel() {
        const p = this.state.payload;
        if (!p) {
            return "";
        }
        if (p.done) {
            return `${p.step_total} / ${p.step_total} complete`;
        }
        return `Step ${Math.min(p.step_index + 1, p.step_total)} of ${p.step_total}`;
    }

    canReopenWizard() {
        const key = this.state.payload?.current_step?.key;
        return INTERACTIVE_WIZARD_KEYS.has(key) && this.state.lastClientAction;
    }

    async onContinue() {
        await this._advance(true);
    }

    async reopenWizard() {
        if (!this.state.lastClientAction) {
            return;
        }
        this._launchClientAction(this.state.lastClientAction);
    }

    async openCase() {
        if (!this._simulationId) {
            return;
        }
        const action = await this.orm.call(
            "bharat.loan.flow.simulation",
            "open_case_action",
            [[this._simulationId]],
        );
        await this._openClientAction(action);
    }

    openInvoice() {
        if (this.state.lastClientAction) {
            this.action.doAction(normalizeWindowAction(this.state.lastClientAction));
            return;
        }
        if (this.state.payload?.invoice_id) {
            this.action.doAction(
                normalizeWindowAction({
                    type: "ir.actions.act_window",
                    name: "Invoice",
                    res_model: "account.move",
                    view_mode: "form",
                    res_id: this.state.payload.invoice_id,
                    target: "new",
                }),
            );
        }
    }

    onExit() {
        this._clearAutoTimer();
        this.action.restore();
    }
}

registry.category("actions").add("bharatnyay_flow_simulation", FlowSimulation);
