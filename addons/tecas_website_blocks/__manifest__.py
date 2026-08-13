{
    'name': 'TECAS Website Blocks',
    'summary': 'Drag-and-drop building blocks for the TECAS website (hero, engagements)',
    'description': """
Mainly building blocks: installing this adds blocks to the website editor and
changes no existing page until one of them is dropped onto a page.

Two deliberate exceptions, each in its own file so they stay easy to find and
to drop: views/shop_filters.xml scopes the shop's attribute filters to the
category being browsed, and static/src/scss/header.scss spaces out the top
menu. Neither changes colours or structure.
""",
    'version': '19.0.7.0.0',
    'depends': ['website', 'website_sale'],
    'data': [
        'views/snippets/s_tecas_hero.xml',
        'views/snippets/s_tecas_engagements.xml',
        'views/snippets/s_tecas_footer.xml',
        'views/snippets/s_tecas_section_head.xml',
        'views/snippets/s_tecas_categories.xml',
        'views/snippets/s_tecas_kits.xml',
        'views/snippets/s_tecas_solutions.xml',
        'views/snippets/snippets.xml',
        'views/shop_filters.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'tecas_website_blocks/static/src/scss/blocks.scss',
            'tecas_website_blocks/static/src/scss/header.scss',
        ],
    },
    'author': 'TECAS',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
