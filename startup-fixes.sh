#!/bin/bash
# Runs after every tecas-web-19 start to ensure DB fixes are applied
echo "Applying startup fixes..."

docker exec tecas-db-19 psql -U odoo19 -d tecas19 -c "
-- Fix product page: broken Studio itemprop/description view
UPDATE ir_ui_view SET active = false 
WHERE arch_db::text ILIKE '%itemprop%' 
  AND arch_db::text ILIKE '%description%';

-- Fix /shop crash
UPDATE ir_ui_view SET active = false 
WHERE arch_db::text ILIKE '%products_attributes_filters%';

-- Delete orphan duplicate website_sale.variants view
DELETE FROM ir_ui_view v USING ir_ui_view v2 WHERE v.key='website_sale.variants' AND v2.key='website_sale.variants' AND v.id > v2.id AND NOT EXISTS (SELECT 1 FROM ir_model_data d WHERE d.model='ir.ui.view' AND d.res_id=v.id);

-- Fix product_details broken view
UPDATE ir_ui_view SET active = false WHERE arch_db::text ILIKE '%product_details%' AND (key ILIKE 'gen_key%' OR name ILIKE '%studio%');

-- Fix website_sale_stock broken product view
DELETE FROM ir_ui_view WHERE id = 2134; UPDATE ir_ui_view SET active = false WHERE id = 4659;

UPDATE ir_ui_view SET active = false WHERE id = 2134;

-- Fix assets
DELETE FROM ir_attachment WHERE url ILIKE '/web/assets%';

-- Fix permissions anchor
UPDATE ir_config_parameter SET value = 'https://19.tecas.ma' WHERE key = 'web.base.url';
UPDATE ir_config_parameter SET value = 'https://19.tecas.ma' WHERE key = 'web.base.url.freeze';
"

docker restart tecas-web-19
sleep 10
docker exec -u root tecas-web-19 chown -R odoo:odoo /var/lib/odoo
echo "Startup fixes applied."
