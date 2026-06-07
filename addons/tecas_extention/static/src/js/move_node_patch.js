/** @odoo-module **/

import { MoveNodePlugin } from "@html_editor/core/move_node_plugin";
import { patch } from "@web/core/utils/patch";

patch(MoveNodePlugin.prototype, {
    destroy() {
        if (!this.observer) {
            return;
        }
        super.destroy(...arguments);
    }
});
