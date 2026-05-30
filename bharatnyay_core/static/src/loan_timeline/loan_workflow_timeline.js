/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const STAGES = [
    { key: "commencement", label: "Commencement", section: "Section 1" },
    { key: "notice", label: "Notice", section: "Section 21" },
    { key: "arbitrator_appointed", label: "Arbitrator Appointed", section: "Section 11" },
    { key: "hearing", label: "Hearing", section: "Section 24" },
    { key: "final_award", label: "Final Arbitration Award", section: "Section 31" },
    { key: "paid", label: "Paid", section: "Section 31" },
];

export class WorkflowTimelineField extends Component {
    static template = "bharatnyay_core.WorkflowTimelineField";
    static props = {
        ...standardFieldProps,
    };

    setup() {}

    get steps() {
        return STAGES;
    }

    get currentStageKey() {
        const v = this.props.record.data[this.props.name];
        if (!v) {
            return STAGES[0].key;
        }
        if (typeof v === "string") {
            return STAGES.some((s) => s.key === v) ? v : STAGES[0].key;
        }
        const section = Number(v);
        const nearest = [...STAGES].sort(
            (a, b) => Math.abs(this.stageSection(a) - section) - Math.abs(this.stageSection(b) - section)
        )[0];
        return nearest?.key || STAGES[0].key;
    }

    stageSection(stage) {
        const match = /(\d+)/.exec(stage.section);
        return match ? Number(match[1]) : 1;
    }

    currentIndex() {
        const idx = STAGES.findIndex((s) => s.key === this.currentStageKey);
        return idx >= 0 ? idx : 0;
    }

    stageClass(idx) {
        if (idx < this.currentIndex()) {
            return "bn-stage-done";
        }
        if (idx === this.currentIndex()) {
            return "bn-stage-active";
        }
        return "bn-stage-pending";
    }

    stageStatusLabel(idx) {
        if (idx < this.currentIndex()) {
            return "DONE";
        }
        if (idx === this.currentIndex()) {
            return "ACTIVE";
        }
        return "PENDING";
    }

    nodeClass(idx) {
        return `bn-stage-node ${this.stageClass(idx)}`;
    }

    connectorClass(idx) {
        return `bn-stage-link ${this.stageClass(idx)}`;
    }

    stageStatusClass(idx) {
        return `bn-stage-state ${this.stageClass(idx)}`;
    }

    isIntegerFieldBinding() {
        const f = this.props.record?.fields?.[this.props.name];
        return f?.type === "integer";
    }

    onPick(stage) {
        if (this.props.readonly) {
            return;
        }
        if (!stage?.key) {
            return;
        }
        if (this.isIntegerFieldBinding()) {
            this.props.record.update({ [this.props.name]: this.stageSection(stage) });
        } else {
            this.props.record.update({ [this.props.name]: stage.key });
        }
    }

    currentPhaseLabel() {
        const stage = STAGES[this.currentIndex()] || STAGES[0];
        return stage.label;
    }

    keyboardNav(ev, stage) {
        if (this.props.readonly) {
            return;
        }
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onPick(stage);
        }
    }
}

registry.category("fields").add("loan_workflow_timeline", {
    component: WorkflowTimelineField,
    supportedTypes: ["selection", "integer"],
    extractProps: () => ({}),
});
