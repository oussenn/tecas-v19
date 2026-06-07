{
    "name": "Product Web Extras (PDF, Web Description, Gallery)",
    "version": "1.4",
    "summary": "Adds tech-sheet PDF, web description, image gallery and hides per-variant prices.",
    "author": "Oussama Ennaciri",
    "license": "LGPL-3",
    "depends": ["sale", "product", "website_sale"],
    "data": [
        "views/product_form.xml",
        "views/website_template.xml",
        "views/hide_variant_price_extra.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tecas_product_webextras/static/src/js/variant_stock_guard.js",
            "tecas_product_webextras/static/src/css/hide_badge.css",
        ],
    },
    "installable": True,
    "application": False,
}
