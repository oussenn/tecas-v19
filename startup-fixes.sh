#!/bin/bash
# TECAS v19 — Startup fixes, runs on every boot via cron
# Idempotent: safe to run multiple times

docker exec tecas-db-19 psql -U odoo19 -d tecas19 <<'SQL'

-- ============================================================
-- PERFORMANCE: clear stuck modules (causes 2s delay per request)
-- ============================================================
UPDATE ir_module_module SET state = 'uninstalled' WHERE state = 'to upgrade';

-- ============================================================
-- CLEANUP: remove broken third-party modules from v16
-- ============================================================
DELETE FROM ir_module_module WHERE name IN (
    'whatsapp_mail_messaging',
    'odoo_n8n_webhook',
    'odoo_whatsapp_integration',
    'product_brand_ecommerce',
    'product_brand_sale'
);

-- ============================================================
-- BROKEN VIEWS: deactivate broken Studio/gen_key views
-- ============================================================

-- /shop 500: products_attributes_filters xpath broken in v19
UPDATE ir_ui_view SET active = false
WHERE arch_db::text ILIKE '%products_attributes_filters%';

-- Product page 500: orphan duplicate alternative_products with old itemprop selector
-- Keep only the lowest id (original), deactivate duplicates
UPDATE ir_ui_view SET active = false
WHERE key = 'website_sale.alternative_products'
AND id != (SELECT MIN(id) FROM ir_ui_view WHERE key = 'website_sale.alternative_products');

-- Product page 500: website_sale_stock xpath targets product_details (removed in v19)
UPDATE ir_ui_view SET active = false
WHERE key = 'website_sale_stock.website_sale_stock_product';

-- Invoice print crash: x_studio_montant_en_lettre_ broken in report context
UPDATE ir_ui_view SET active = false
WHERE arch_db::text ILIKE '%x_studio_montant_en_lettre_%'
AND arch_db::text ILIKE '%report%';

-- Devis print crash: t-elif without t-if (gen_key.ca61e6)
-- Hide Variant Badge Extra Price crash (gen_key.7a9bdc, gen_key.6ad26c)
UPDATE ir_ui_view SET active = false
WHERE key IN ('gen_key.ca61e6', 'gen_key.7a9bdc', 'gen_key.6ad26c');

-- Hide Variant Badge Extra Price (name-based fallback)
UPDATE ir_ui_view SET active = false
WHERE name ILIKE '%Hide Variant Badge Extra Price%';

-- ============================================================
-- BROKEN VIEWS: fix badge_extra_price KeyError 'attribute'
-- ============================================================
UPDATE ir_ui_view SET arch_db = jsonb_set(
    arch_db,
    '{en_US}',
    to_jsonb('<t t-name="website_sale.badge_extra_price"><t></t></t>'::text)
)
WHERE key = 'website_sale.badge_extra_price'
AND arch_db::text ILIKE '%attribute.display_type%';

-- ============================================================
-- DUPLICATE VIEWS: delete orphan duplicates with no ir_model_data
-- ============================================================
DELETE FROM ir_ui_view
WHERE key = 'website_sale.variants'
AND id != (SELECT MIN(id) FROM ir_ui_view WHERE key = 'website_sale.variants');

-- ============================================================
-- BASE URLS
-- ============================================================
INSERT INTO ir_config_parameter (key, value)
VALUES ('web.base.url', 'https://19.tecas.ma')
ON CONFLICT (key) DO UPDATE SET value = 'https://19.tecas.ma';

INSERT INTO ir_config_parameter (key, value)
VALUES ('report.url', 'http://localhost:8069')
ON CONFLICT (key) DO UPDATE SET value = 'http://localhost:8069';

-- ============================================================
-- DB FIXES
-- ============================================================

-- Fix wkhtmltopdf/trigram index warnings
ALTER FUNCTION unaccent(text) IMMUTABLE;

-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Fix broken Studio-copied invoice report templates (formatted_amount KeyError in v19)
UPDATE ir_act_report_xml SET report_name = 'account.report_invoice_with_payments'
WHERE report_name ILIKE '%copy%' AND report_name ILIKE '%invoice_with_payments%';

-- Clear compiled assets cache
DELETE FROM ir_attachment WHERE url ILIKE '/web/assets%';

SQL

docker restart tecas-web-19 > /dev/null 2>&1
sleep 12
docker exec -u root tecas-web-19 chown -R odoo:odoo /var/lib/odoo

# ============================================================
# CHROME 109 / WINDOWS 7 COMPATIBILITY POLYFILL
# Array.prototype.toReversed missing in Chrome < 110
# ============================================================
POLYFILL_FILE="/opt/tecas-v19/addons/tecas_extention/static/src/js/array_polyfill.js"

if [ ! -f "$POLYFILL_FILE" ]; then
    echo "[startup-fixes] Writing array_polyfill.js..."
    cat > "$POLYFILL_FILE" << 'JSEOF'
/** @odoo-module **/
(function() {
    if (typeof Array.prototype.toReversed === 'undefined') {
        Object.defineProperty(Array.prototype, 'toReversed', {
            value: function toReversed() {
                return Array.prototype.slice.call(this).reverse();
            },
            writable: true,
            configurable: true,
            enumerable: false
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
# ============================================================
STATUSBAR_FIX="/opt/tecas-v19/addons/tecas_extention/static/src/css/statusbar_fix.css"

if [ ! -f "$STATUSBAR_FIX" ]; then
    echo "[startup-fixes] Writing statusbar_fix.css..."
    cat > "$STATUSBAR_FIX" << 'CSSEOF'
.o_arrow_button::before {
    background-color: transparent !important;
    background: transparent !important;
}
CSSEOF
    echo "[startup-fixes] statusbar_fix.css written."
else
    echo "[startup-fixes] statusbar_fix.css already exists, skipping."
fi
