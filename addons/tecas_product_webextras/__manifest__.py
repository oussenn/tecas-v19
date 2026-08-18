{
    "name": "TECAS - Product Web Extras & Variant Shop",
    "version": "19.0.3.0.0",
    "summary": "Per-variant web description, datasheet and gallery, plus one shop tile per variant.",
    "description": """
Two halves of the same job — presenting variants properly on the website.

**Web extras.** Adds a web description, a technical datasheet (PDF) and an image
gallery to products. Anything set on the product applies to all of its variants;
a variant can override the name, description, datasheet or gallery on its own
form, and the website follows the visitor's variant selection live.

**Variant shop.** Lists one tile per variant on /shop instead of one per
product, sellable stock first and out-of-stock last, dimmed and flagged.
Controlled per website by "Split variants in the shop" (Website > Configuration
> Settings > Shop); turning it off restores stock Odoo behaviour.
    """,
    "author": "Oussama Ennaciri",
    "license": "LGPL-3",
    "category": "Website/Website",
    "depends": ["sale", "product", "website_sale", "stock"],
    "data": [
        "views/product_form.xml",
        "views/website_template.xml",
        "views/website_sale_templates.xml",
        "views/res_config_settings_views.xml",
        "views/hide_variant_price_extra.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tecas_product_webextras/static/src/js/variant_stock_guard.js",
            "tecas_product_webextras/static/src/js/webextras_variant.js",
            "tecas_product_webextras/static/src/css/hide_badge.css",
            "tecas_product_webextras/static/src/scss/variants.scss",
        ],
    },
    "installable": True,
    "application": False,
}
