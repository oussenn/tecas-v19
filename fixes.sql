
-- Fix product page crash (broken Studio itemprop/description view)
UPDATE ir_ui_view SET active = false 
WHERE arch_db::text ILIKE '%itemprop%' 
  AND arch_db::text ILIKE '%description%';
