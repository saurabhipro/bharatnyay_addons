/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class PostalDeliveryCardsField extends Component {
    static template = "bharatnyay_core.PostalDeliveryCardsField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
    }

    get cards() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return [];
        }
        try {
            const data = typeof raw === "string" ? JSON.parse(raw) : raw;
            return Array.isArray(data?.cards) ? data.cards : [];
        } catch {
            return [];
        }
    }

    cardClass(card) {
        const classes = [
            "bn-postal-card",
            `bn-postal-card--${card.state}`,
            `bn-postal-card--${card.document_type}`,
        ];
        if (card.clickable) {
            classes.push("bn-postal-card--clickable");
        }
        return classes.join(" ");
    }

    onCardClick(ev, card) {
        ev.preventDefault();
        ev.stopPropagation();
        void this._openPostalWizard(card);
    }

    async _openPostalWizard(card) {
        if (!card?.clickable) {
            return;
        }
        const record = this.props.record;
        const recordId = record.resId;
        if (!recordId || !card.document_type) {
            return;
        }
        try {
            let act;
            if (record.resModel === "bharat.loan.notice.line") {
                act = await this.orm.call(
                    "bharat.loan.notice.line",
                    "action_update_pod",
                    [[recordId]]
                );
            } else {
                act = await this.orm.call(
                    "bharat.loan",
                    "action_open_postal_status_wizard",
                    [[recordId], card.document_type]
                );
            }
            if (!act) {
                return;
            }
            if (!act.views && act.view_mode) {
                act.views = act.view_mode.split(",").map((mode) => [false, mode.trim()]);
            }
            await this.action.doAction(act, {
                onClose: () => this.props.record.load(),
            });
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }
}

registry.category("fields").add("bn_postal_delivery_cards", {
    component: PostalDeliveryCardsField,
    supportedTypes: ["json"],
});
