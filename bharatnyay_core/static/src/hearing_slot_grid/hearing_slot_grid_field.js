/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class HearingSlotGridField extends Component {
    static template = "bharatnyay_core.HearingSlotGridField";
    static props = {
        "*": true,
    };

    get readonly() {
        return Boolean(this.props.readonly);
    }

    slotKind(slot) {
        if (slot.status) {
            return slot.status;
        }
        return slot.available ? "free" : "booked";
    }

    /** Server sends status: free | booked | unavailable */
    isFree(slot) {
        return this.slotKind(slot) === "free";
    }

    isDisabled(slot) {
        return !this.isFree(slot) || this.readonly;
    }

    get slots() {
        try {
            const raw = this.props.record.data.slot_board_json;
            const parsed = typeof raw === "string" ? JSON.parse(raw || "{}") : raw || {};
            return Array.isArray(parsed.slots) ? parsed.slots : [];
        } catch {
            return [];
        }
    }

    cellClass(slot) {
        const selected = this.props.record.data.grid_selected_index;
        const classes = ["bn-slot-cell"];
        const kind = this.slotKind(slot);
        if (kind === "booked") {
            classes.push("bn-slot-cell--booked");
        } else if (kind === "unavailable") {
            classes.push("bn-slot-cell--unavailable");
        } else {
            classes.push("bn-slot-cell--free");
        }
        if (slot.index === selected && this.isFree(slot)) {
            classes.push("bn-slot-cell--selected");
        }
        return classes.join(" ");
    }

    slotIconClass(slot) {
        const kind = this.slotKind(slot);
        if (kind === "booked") {
            return "fa fa-times-circle bn-slot-ico";
        }
        if (kind === "unavailable") {
            return "fa fa-clock-o bn-slot-ico";
        }
        return "fa fa-check-circle bn-slot-ico";
    }

    slotTitle(slot) {
        const kind = this.slotKind(slot);
        if (kind === "booked") {
            const loan = slot.loan_number ? ` · ${slot.loan_number}` : "";
            return `Slot ${slot.index} (${slot.label}) — booked${loan}`;
        }
        if (kind === "unavailable") {
            return `Slot ${slot.index} (${slot.label}) — unavailable`;
        }
        if (slot.index === this.props.record.data.grid_selected_index) {
            return `Slot ${slot.index} (${slot.label}) — selected`;
        }
        return `Slot ${slot.index} (${slot.label}) — free`;
    }

    slotRangeLabel(slot) {
        const parts = (slot.label || "").split(":");
        if (parts.length !== 2) {
            return slot.label || "";
        }
        const h = parseInt(parts[0], 10);
        const m = parseInt(parts[1], 10);
        if (Number.isNaN(h) || Number.isNaN(m)) {
            return slot.label || "";
        }
        const endMin = h * 60 + m + 30;
        const eh = Math.floor(endMin / 60);
        const em = endMin % 60;
        const end = `${String(eh).padStart(2, "0")}:${String(em).padStart(2, "0")}`;
        return `${slot.label}–${end}`;
    }

    onSelectClick(slot) {
        return (ev) => {
            ev.preventDefault();
            this.onSelect(slot);
        };
    }

    onSelect(slot) {
        if (!this.isFree(slot) || this.readonly) {
            return;
        }
        if (this.props.record.data.grid_selected_index === slot.index) {
            return;
        }
        // Client-side only — server onchange on grid index caused infinite RPC loops.
        this.props.record.update(
            {
                grid_selected_index: slot.index,
                selected_slot_range_display: this.slotRangeLabel(slot),
            },
            { withoutOnchange: true }
        );
    }
}

registry.category("fields").add("bn_hearing_slot_grid", {
    component: HearingSlotGridField,
    supportedTypes: ["integer"],
});
