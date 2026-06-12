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

    async onCardClick(card) {
        return async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            if (!card?.clickable) {
                return;
            }
            const loanId = this.props.record.resId;
            if (!loanId || !card.document_type) {
                return;
            }
            try {
                const act = await this.orm.call(
                    "bharat.loan",
                    "action_open_postal_status_wizard",
                    [[loanId], card.document_type]
                );
                await this.action.doAction(act, {
                    onClose: () => this.props.record.load(),
                });
            } catch (e) {
                this.notification.add(e.message || String(e), { type: "danger" });
            }
        };
    }
}

registry.category("fields").add("bn_postal_delivery_cards", {
    component: PostalDeliveryCardsField,
    supportedTypes: ["json"],
});
