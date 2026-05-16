/** @odoo-module **/

import { AlignPlugin } from "@html_editor/core/align_plugin";
import { patch } from "@web/core/utils/patch";

patch(AlignPlugin.prototype, {
    updateAlignmentParams(params) {
        if (!params || !params.anchorNode) {
            return;
        }
        super.updateAlignmentParams(...arguments);
    }
});
