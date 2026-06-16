/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { X2ManyField } from "@web/views/fields/x2many/x2many_field";

patch(X2ManyField.prototype, {
    setup() {
        super.setup(...arguments);
        const openRecord = this._openRecord.bind(this);
        this._openRecord = (params) => {
            if (params?.record && this.list?.resModel === "bharat.loan.notice.line") {
                const data = params.record.data;
                const title =
                    data.notice_label ||
                    (data.notice_number ? `Notice ${data.notice_number}` : null);
                if (title) {
                    params = { ...params, title };
                }
            }
            return openRecord(params);
        };
    },
});
