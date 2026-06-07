/** @odoo-module **/

import VariantMixin from '@website_sale_stock/js/variant_mixin';

const _orig = VariantMixin._onChangeCombinationStock;

VariantMixin._onChangeCombinationStock = async function (ev, parent, combination) {
    if (!this.el) return;
    if (!combination.is_storable && !('max_combo_quantity' in combination)) return;
    const availMsg = this.el.querySelector('div.availability_messages');
    if (!availMsg) return;
    return _orig.call(this, ev, parent, combination);
};
