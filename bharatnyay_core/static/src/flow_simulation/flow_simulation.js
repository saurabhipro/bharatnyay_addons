/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const INTERACTIVE_WIZARD_KEYS = new Set([
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
            phase: "pick_mode",
            advanceMode: null,
            loading: false,
            error: null,
            payload: null,
            message: "",
            busy: false,
            waitingForUser: false,
            readyForNext: false,
            autoWaiting: false,
            lastClientAction: null,
            videoRoomUrl: "",
        });

        this._autoTimer = null;
        this._simulationId = null;

        onWillStart(() => {
            this.state.loading = false;
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

    async startDemo(mode) {
        if (this.state.busy || this.state.phase !== "pick_mode") {
            return;
        }
        this.state.busy = true;
        this.state.advanceMode = mode;
        this.state.phase = "running";
        this.state.loading = true;
        this.state.error = null;
        try {
            await this._bootstrap();
        } finally {
            this.state.busy = false;
        }
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
            this.state.readyForNext = true;
            if (this.state.advanceMode === "auto") {
                await this._advance(false);
            }
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
        if (payload?.open_url) {
            this._openDemoUrl(payload.open_url);
            this.state.videoRoomUrl = payload.open_url;
        }
    }

    _openDemoUrl(url) {
        const target = (url || "").trim();
        if (!target) {
            return;
        }
        window.open(target, "_blank", "noopener,noreferrer");
    }

    async _advance(confirmed = false) {
        if (!this._simulationId || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.waitingForUser = false;
        this.state.readyForNext = false;
        this.state.autoWaiting = false;
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
                await this._finishDemo(payload);
                return;
            }
            if (payload.wait && payload.client_action) {
                this.state.waitingForUser = true;
                this.state.readyForNext = true;
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
                this.state.readyForNext = true;
                if (this.state.advanceMode === "manual") {
                    return;
                }
                this.state.autoWaiting = true;
                await this._sleep(payload.auto_pause_ms || 1400);
                if (!this.state.autoWaiting) {
                    return;
                }
                this.state.autoWaiting = false;
                await this._advance(false);
                return;
            }
            this.state.readyForNext = true;
        } catch (e) {
            this.state.error = e?.message || String(e);
            this.notification.add(this.state.error, { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async _finishDemo(payload) {
        const label = payload?.loan_label || "Demo case";
        const parts = [`${label}: guided demo complete.`];
        if (payload?.invoice_name) {
            parts.push(`Invoice ${payload.invoice_name} created.`);
        }
        this.notification.add(parts.join(" "), {
            title: "Flow demo complete",
            type: "success",
        });
        await this._sleep(900);
        this.onExit();
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

    isAutoStep() {
        return this.state.payload?.current_step?.mode === "auto";
    }

    nextButtonLabel() {
        if (this.state.waitingForUser) {
            return "Continue";
        }
        return "Next";
    }

    nextHint() {
        if (this.state.busy) {
            return "Working…";
        }
        if (this.state.advanceMode === "manual") {
            if (this.state.waitingForUser) {
                return "Complete the action above, then click Continue.";
            }
            return "Click Next when you are ready to run this step.";
        }
        if (this.state.autoWaiting) {
            return "Auto-advancing… click Next to skip the pause.";
        }
        if (this.state.waitingForUser) {
            return "Complete the action above, then click Continue.";
        }
        if (this.isAutoStep()) {
            return "Click Next to run this step now, or wait for auto-advance.";
        }
        return "Click Next to move to the following step.";
    }

    canShowNext() {
        return Boolean(
            this.state.payload &&
                !this.state.payload.done &&
                (this.state.readyForNext || this.state.waitingForUser || this.state.autoWaiting),
        );
    }

    async onNext() {
        if (!this.canShowNext() || this.state.busy) {
            return;
        }
        this._clearAutoTimer();
        this.state.autoWaiting = false;
        await this._advance(this.state.waitingForUser);
    }

    async onContinue() {
        await this.onNext();
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

    openVideoRoom() {
        this._openDemoUrl(this.state.videoRoomUrl || this.state.payload?.open_url);
    }

    onExit() {
        this._clearAutoTimer();
        this.action.restore();
    }
}

registry.category("actions").add("bharatnyay_flow_simulation", FlowSimulation);
