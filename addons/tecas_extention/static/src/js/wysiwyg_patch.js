/** @odoo-module **/

import { EmbeddedComponentPlugin } from "@html_editor/others/embedded_component_plugin";
import { patch } from "@web/core/utils/patch";

patch(EmbeddedComponentPlugin.prototype, {
    destroy() {
        if (!this.components || typeof this.components[Symbol.iterator] !== 'function') {
            return;
        }
        super.destroy(...arguments);
    }
});
