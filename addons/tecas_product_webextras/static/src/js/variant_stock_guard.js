/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { WebsiteSale } from '@website_sale/interactions/website_sale';

patch(WebsiteSale.prototype, {
    async _onChangeCombinationStock(ev, parent, combination) {
        if (!this.el || !parent) return;
        if (!parent.querySelector('#o_wsale_cta_wrapper')) return;
        if (!this.el.querySelector('div.availability_messages')) return;
        return super._onChangeCombinationStock(ev, parent, combination);
    }
});
