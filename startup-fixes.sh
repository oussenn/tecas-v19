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
