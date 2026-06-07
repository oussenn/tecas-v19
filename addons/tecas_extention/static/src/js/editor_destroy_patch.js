/** @odoo-module **/

import { Editor } from "@html_editor/editor";
import { patch } from "@web/core/utils/patch";

patch(Editor.prototype, {
    destroy() {
        for (const plugin of this.plugins || []) {
            try {
                plugin.destroy();
            } catch (e) {
                console.warn("[tecas] Editor plugin destroy error suppressed:", plugin.constructor?.name, e);
            }
        }
        // Mark plugins as already destroyed so parent destroy() skips them
        this.plugins = [];
        try {
            super.destroy(...arguments);
        } catch (e) {
            console.warn("[tecas] Editor.destroy error suppressed:", e);
        }
    }
});
