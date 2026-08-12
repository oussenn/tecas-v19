/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { markup } from '@odoo/owl';
import { WebsiteSale } from '@website_sale/interactions/website_sale';

/**
 * Keep the web extras in step with the selected variant.
 *
 * The server ships the resolved values (variant override, else the product's)
 * inside the combination info, so this only has to move them into the DOM.
 */
patch(WebsiteSale.prototype, {
    _onChangeCombination(ev, parent, combination) {
        const res = super._onChangeCombination(ev, parent, combination);
        if (!('webx_description' in combination)) {
            return res;
        }

        const name = document.getElementById('o_tecas_webx_name');
        if (name && combination.webx_name) {
            name.textContent = combination.webx_name;
        }

        const description = document.getElementById('o_tecas_webx_description');
        if (description) {
            const body = description.querySelector('.o_tecas_webx_description_body');
            if (body) {
                body.innerHTML = '';
                if (combination.webx_description) {
                    body.append(...this._webxParse(combination.webx_description));
                }
            }
            description.classList.toggle('d-none', !combination.webx_description);
        }

        const techSheet = document.getElementById('o_tecas_webx_techsheet');
        if (techSheet) {
            const link = techSheet.querySelector('.o_tecas_webx_techsheet_link');
            if (link) {
                link.setAttribute('href', combination.webx_tech_sheet_url || '#');
            }
            techSheet.classList.toggle('d-none', !combination.webx_tech_sheet_url);
        }

        const gallery = document.getElementById('o_tecas_webx_gallery');
        if (gallery) {
            const body = gallery.querySelector('.o_tecas_webx_gallery_body');
            const images = combination.webx_gallery || [];
            if (body) {
                body.replaceChildren(...images.map((image) => this._webxGalleryItem(image)));
            }
            gallery.classList.toggle('d-none', !images.length);
        }

        return res;
    },

    /**
     * The description is author-controlled HTML sanitised server-side by the
     * Html field, so it is parsed rather than assigned, to keep it out of
     * innerHTML on the hot path.
     */
    _webxParse(html) {
        const template = document.createElement('template');
        template.innerHTML = markup(html).toString();
        return [...template.content.childNodes];
    },

    _webxGalleryItem(image) {
        const col = document.createElement('div');
        col.className = 'col-4 col-md-3 mb-3';
        const link = document.createElement('a');
        link.href = `/web/content/${image.id}?download=0`;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = `/web/image/${image.id}`;
        img.className = 'img-fluid rounded shadow-sm';
        img.alt = image.name || '';
        link.append(img);
        col.append(link);
        return col;
    },
});
