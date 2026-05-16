#!/bin/bash
# TECAS v19 — Startup fixes, runs on every boot via cron
# Idempotent: safe to run multiple times

docker exec tecas-db-19 psql -U odoo19 -d tecas19 <<'SQL'

-- Speed: clear stuck modules
UPDATE ir_module_module SET state = 'uninstalled' WHERE state = 'to upgrade';

-- Remove broken third-party modules from v16
DELETE FROM ir_module_module WHERE name IN (
    'whatsapp_mail_messaging',
    'odoo_n8n_webhook',
    'odoo_whatsapp_integration',
    'product_brand_ecommerce',
    'product_brand_sale'
);

-- Deactivate broken Studio/gen_key views
UPDATE ir_ui_view SET active = false WHERE arch_db::text ILIKE '%products_attributes_filters%';
UPDATE ir_ui_view SET active = false WHERE arch_db::text ILIKE '%itemprop%' AND arch_db::text ILIKE '%description%';
UPDATE ir_ui_view SET active = false WHERE arch_db::text ILIKE '%x_studio_montant_en_lettre_%';
UPDATE ir_ui_view SET active = false WHERE arch_db::text ILIKE '%product_details%' AND (key ILIKE 'gen_key%' OR name ILIKE '%studio%');
UPDATE ir_ui_view SET active = false WHERE name ILIKE '%Hide Variant Badge Extra Price%';
UPDATE ir_ui_view SET active = false WHERE key IN ('gen_key.ca61e6', 'gen_key.7a9bdc', 'gen_key.6ad26c');

-- Delete orphan duplicate views (same key, no ir_model_data entry)
DELETE FROM ir_ui_view
WHERE key IN ('website_sale.variants', 'website_sale_stock.website_sale_stock_product')
  AND NOT EXISTS (
      SELECT 1 FROM ir_model_data d
      WHERE d.model = 'ir.ui.view' AND d.res_id = ir_ui_view.id
  );

-- Base URLs
UPDATE ir_config_parameter SET value = 'https://19.tecas.ma' WHERE key = 'web.base.url';
UPDATE ir_config_parameter SET value = 'https://19.tecas.ma' WHERE key = 'web.base.url.freeze';

-- Fix wkhtmltopdf report rendering (proxy_mode needs localhost for PDF generation)
INSERT INTO ir_config_parameter (key, value)
VALUES ('report.url', 'http://localhost:8069')
ON CONFLICT (key) DO UPDATE SET value = 'http://localhost:8069';

-- Fix unaccent immutability (fixes trigram index warnings)
ALTER FUNCTION unaccent(text) IMMUTABLE;

-- pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Clear compiled assets cache
DELETE FROM ir_attachment WHERE url ILIKE '/web/assets%';

SQL

docker restart tecas-web-19 > /dev/null 2>&1
sleep 12
docker exec -u root tecas-web-19 chown -R odoo:odoo /var/lib/odoo

# ============================================================
# CHROME 109 / WINDOWS 7 COMPATIBILITY POLYFILL
# Array.prototype.toReversed missing in Chrome < 110
# Must be present in tecas_extention/static/src/js/array_polyfill.js
# ============================================================
POLYFILL_FILE="/opt/tecas-v19/addons/tecas_extention/static/src/js/array_polyfill.js"

if [ ! -f "$POLYFILL_FILE" ]; then
    echo "[startup-fixes] Writing array_polyfill.js..."
    cat > "$POLYFILL_FILE" << 'JSEOF'
/** @odoo-module **/

// Safe polyfill for Chrome 109 (Windows 7) - only toReversed is needed by Odoo 19 HistoryPlugin
// We patch Array.prototype only if missing, no other methods touched
(function() {
    if (typeof Array.prototype.toReversed === 'undefined') {
        Object.defineProperty(Array.prototype, 'toReversed', {
            value: function toReversed() {
                return Array.prototype.slice.call(this).reverse();
            },
            writable: true,
            configurable: true,
            enumerable: false  // critical: non-enumerable so for...in loops are unaffected
        });
    }
})();
JSEOF
    echo "[startup-fixes] array_polyfill.js written."
else
    echo "[startup-fixes] array_polyfill.js already exists, skipping."
fi

# ============================================================
# CHROME 109 / WINDOWS 7 — STATUSBAR ::before WHITE OVERLAY FIX
# ::before pseudo-element renders as solid white on Chrome 109,
# covering button text. Fix: force transparent background.
# ============================================================
STATUSBAR_FIX="/opt/tecas-v19/addons/tecas_extention/static/src/css/statusbar_fix.css"

if [ ! -f "$STATUSBAR_FIX" ]; then
    echo "[startup-fixes] Writing statusbar_fix.css..."
    cat > "$STATUSBAR_FIX" << 'CSSEOF'
/* Chrome 109 / Windows 7
   ::before pseudo-element renders as solid white, covering button text.
   Fix: force it transparent across all statusbar instances. */

.o_arrow_button::before {
    background-color: transparent !important;
    background: transparent !important;
}
CSSEOF
    echo "[startup-fixes] statusbar_fix.css written."
else
    echo "[startup-fixes] statusbar_fix.css already exists, skipping."
fi
