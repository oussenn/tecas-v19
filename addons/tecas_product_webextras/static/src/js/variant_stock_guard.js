import VariantMixin from '@website_sale/js/variant_mixin';
import { renderToFragment } from '@web/core/utils/render';

const origOnChangeCombinationStock = VariantMixin._onChangeCombinationStock;

VariantMixin._onChangeCombinationStock = async function (ev, parent, combination) {
    try {
        const el = this.el?.querySelector?.('div.availability_messages');
        if (!el) return;
        return await origOnChangeCombinationStock.call(this, ev, parent, combination);
    } catch (e) {
        console.warn('[tecas] variant stock update skipped:', e);
    }
};
