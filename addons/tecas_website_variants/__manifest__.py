{
    'name': 'TECAS - Variants as shop products',
    'summary': 'List every product variant as its own card on the shop page',
    'description': """
Splits the shop listing so that each product variant gets its own tile instead of
one tile per product template. Variants that are out of stock stay visible but are
dimmed and flagged.

Controlled per website by "Split variants in the shop" (Website > Configuration >
Settings > Shop). Turning it off restores the standard Odoo behaviour without
uninstalling.
    """,
    'version': '19.0.1.0.0',
    'category': 'Website/Website',
    'author': 'TECAS Energie Solaire',
    'license': 'LGPL-3',
    'depends': ['website_sale', 'stock'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/website_sale_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'tecas_website_variants/static/src/scss/variants.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
}
