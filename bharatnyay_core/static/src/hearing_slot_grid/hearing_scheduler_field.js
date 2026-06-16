/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDate } from "@web/core/l10n/dates";

export class HearingSchedulerField extends Component {
    static template = "bharatnyay_core.HearingSchedulerField";
    static props = {
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
    }

    _toISODate(value) {
        if (!value) {
            return "";
        }
        if (typeof value === "string") {
            return value.slice(0, 10);
        }
        if (typeof value.toISODate === "function") {
            return value.toISODate();
        }
        if (typeof value.plus === "function") {
            return value.toFormat("yyyy-MM-dd");
        }
        return "";
    }

    get readonly() {
        return Boolean(this.props.readonly);
    }

    get viewMode() {
        return this.props.record.data.scheduler_view_mode || "week";
    }

    get isWeekView() {
        return this.viewMode === "week";
    }

    get weekStartISO() {
        const cal = this.props.record.data.calendar_week_start;
        if (cal) {
            return cal;
        }
        const fromBoard = this.weekBoard.week_start;
        if (fromBoard) {
            return fromBoard;
        }
        return this._toISODate(this.props.record.data.scheduler_week_start);
    }

    slotKind(slot) {
        if (slot?.status) {
            return slot.status;
        }
        return slot?.available ? "free" : "booked";
    }

    isFree(slot) {
        const kind = this.slotKind(slot);
        return kind === "free" || kind === "own";
    }

    isDisabled(slot) {
        return !this.isFree(slot) || this.readonly;
    }

    get daySlots() {
        try {
            const raw = this.props.record.data.slot_board_json;
            const parsed = typeof raw === "string" ? JSON.parse(raw || "{}") : raw || {};
            return Array.isArray(parsed.slots) ? parsed.slots : [];
        } catch {
            return [];
        }
    }

    get weekBoard() {
        try {
            const raw = this.props.record.data.week_board_json;
            return typeof raw === "string" ? JSON.parse(raw || "{}") : raw || {};
        } catch {
            return {};
        }
    }

    get currentHearing() {
        return this.weekBoard.current_hearing || null;
    }

    isCurrentHearingSlot(slot, dayDate) {
        const marker = this.currentHearing;
        if (!marker || !marker.in_grid || !slot) {
            return false;
        }
        return (
            this._toISODate(dayDate) === marker.date &&
            slot.index === marker.slot_index
        );
    }

    get weekDays() {
        return Array.isArray(this.weekBoard.days) ? this.weekBoard.days : [];
    }

    get weekTitle() {
        const name = this.weekBoard.arbitrator_name || "Arbitrator";
        const start = this.weekBoard.week_start || "";
        const end = this.weekBoard.week_end || "";
        if (start && end) {
            return `${name} · ${start} – ${end}`;
        }
        return name;
    }

    get timeRows() {
        const firstDay = this.weekDays[0];
        if (!firstDay?.slots?.length) {
            return [];
        }
        return firstDay.slots.map((slot) => ({
            index: slot.index,
            label: slot.label,
        }));
    }

    slotAt(day, index) {
        return (day.slots || []).find((s) => s.index === index) || null;
    }

    cellClass(slot, dayDate) {
        const classes = ["bn-slot-cell"];
        const kind = this.slotKind(slot);
        if (kind === "booked") {
            classes.push("bn-slot-cell--booked");
        } else if (kind === "own") {
            classes.push("bn-slot-cell--own");
        } else if (kind === "unavailable") {
            classes.push("bn-slot-cell--unavailable");
        } else {
            classes.push("bn-slot-cell--free");
        }
        if (this.isCurrentHearingSlot(slot, dayDate)) {
            classes.push("bn-slot-cell--current-hearing");
        }
        if (this.isSelected(slot, dayDate)) {
            classes.push("bn-slot-cell--selected");
        }
        return classes.join(" ");
    }

    isSelected(slot, dayDate) {
        if (!slot) {
            return false;
        }
        const kind = this.slotKind(slot);
        const selectedDate =
            this.props.record.data.grid_selected_date ||
            this._toISODate(this.props.record.data.scheduler_date);
        const selectedIndex = this.props.record.data.grid_selected_index;
        const sameCell =
            this._toISODate(selectedDate) === this._toISODate(dayDate) &&
            slot.index === selectedIndex;
        if (sameCell && (kind === "free" || kind === "own")) {
            return true;
        }
        return this.isCurrentHearingSlot(slot, dayDate) && kind === "own";
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

    slotTitle(slot, day) {
        if (!slot) {
            return "";
        }
        const kind = this.slotKind(slot);
        const prefix = day?.label ? `${day.label} ` : "";
        if (kind === "booked" || kind === "own") {
            const loan = slot.loan_number ? ` · ${slot.loan_number}` : "";
            const slotNo = slot.index ? ` · Slot ${slot.index}` : "";
            const tag = kind === "own" ? "your hearing" : "booked";
            return `${prefix}${slot.label}${slotNo} — ${tag}${loan}`;
        }
        if (kind === "unavailable") {
            return `${prefix}${slot.label} — unavailable`;
        }
        return `${prefix}${slot.label} — free`;
    }

    slotRangeLabel(slot) {
        if (slot?.time_range) {
            return slot.time_range;
        }
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

    displayLabel(slot, day) {
        return `${day.label} ${this.slotRangeLabel(slot)}`;
    }

    onWeekCellClick(ev, slot, day) {
        ev.preventDefault();
        this.onSelectSlot(slot, day.date, day);
    }

    onDayCellClick(ev, slot) {
        ev.preventDefault();
        this.onSelectSlot(slot, this._toISODate(this.props.record.data.scheduler_date), null);
    }

    onSelectSlot(slot, dayDate, dayMeta) {
        if (!this.isFree(slot) || this.readonly || !dayDate) {
            return;
        }
        const dateIso = this._toISODate(dayDate);
        if (!dateIso) {
            return;
        }
        const range = dayMeta
            ? this.displayLabel(slot, dayMeta)
            : this.slotRangeLabel(slot);
        const selectionLabel = dayMeta
            ? `${dayMeta.label} · ${this.slotRangeLabel(slot)}`
            : `${dateIso} · ${range}`;
        this.props.record.update(
            {
                grid_selected_index: slot.index,
                grid_selected_date: dateIso,
                selected_slot_range_display: range,
                scheduler_selection_label: selectionLabel,
            },
            { withoutOnchange: true }
        );
    }

    shiftWeek(delta) {
        const iso = this.weekStartISO;
        if (!iso) {
            return;
        }
        const start = deserializeDate(iso);
        if (!start) {
            return;
        }
        const nextISO = start.plus({ days: 7 * delta }).toISODate();
        this.props.record.update(
            {
                calendar_week_start: nextISO,
                grid_selected_index: 0,
                grid_selected_date: "",
                selected_slot_range_display: "",
                scheduler_selection_label: "Choose a time on the calendar below",
            },
            { withoutOnchange: true }
        );
        void this._reloadWeekBoard(nextISO);
    }

    async _reloadWeekBoard(weekStr) {
        const loanRaw = this.props.record.data.loan_id;
        const loanId = Array.isArray(loanRaw) ? loanRaw[0] : loanRaw;
        if (!loanId || !weekStr) {
            return;
        }
        const board = await this.orm.call(
            "bharat.loan.hearing.schedule.wizard",
            "get_week_board_json_for_context",
            [loanId, weekStr]
        );
        if (board) {
            await this.props.record.update(
                { week_board_json: board },
                { withoutOnchange: true }
            );
        }
    }

    onPrevWeek() {
        this.shiftWeek(-1);
    }

    onNextWeek() {
        this.shiftWeek(1);
    }
}

registry.category("fields").add("bn_hearing_scheduler", {
    component: HearingSchedulerField,
    supportedTypes: ["integer"],
});
