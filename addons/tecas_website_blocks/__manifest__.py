{
    'name': 'TECAS Website Blocks',
    'summary': 'Drag-and-drop building blocks for the TECAS website (hero, engagements)',
    'description': """
Mainly building blocks: installing this adds blocks to the website editor and
changes no existing page until one of them is dropped onto a page.

The deliberate exceptions live one per file so they stay easy to find and to
drop: views/shop_filters.xml scopes the shop's attribute filters to the
category being browsed, views/products_menu.xml supplies the panel that
models/tecas_autosync.py stores in the "Nos Produits" mega menu, the
tecas_show_when_empty flag on product.public.category lets a family be browsed
before its products are published, and the two SCSS files dress the top menu
(header) and shrink the sub-category strip on category pages (shop).
""",
    'version': '19.0.35.0.0',
    'depends': ['website', 'website_sale', 'website_blog'],
    'data': [
        'views/snippets/s_tecas_hero.xml',
        'views/snippets/s_tecas_engagements.xml',
        'views/snippets/s_tecas_footer.xml',
        'views/snippets/s_tecas_section_head.xml',
        'views/snippets/s_tecas_categories.xml',
        'views/snippets/s_tecas_kits.xml',
        'views/snippets/s_tecas_solutions.xml',
        'views/snippets/s_tecas_steps.xml',
        'views/snippets/s_tecas_why.xml',
        'views/snippets/s_tecas_services.xml',
        'views/snippets/s_tecas_reviews.xml',
        'views/snippets/s_tecas_news.xml',
        'views/snippets/s_tecas_brands.xml',
        'views/snippets/snippets.xml',
        'views/products_menu.xml',
        'views/shop_filters.xml',
        'views/shop_filmstrip.xml',
        'views/shop_prices_login.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'tecas_website_blocks/static/src/scss/blocks.scss',
            'tecas_website_blocks/static/src/scss/header.scss',
            'tecas_website_blocks/static/src/scss/shop.scss',
            'tecas_website_blocks/static/src/js/carousel.js',
        ],
    },
    'author': 'TECAS',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
