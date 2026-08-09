{
    'name': 'TECAS Website Blocks',
    'summary': 'Drag-and-drop building blocks for the TECAS website (hero, engagements)',
    'description': """
Building blocks only. This module deliberately does NOT touch the header, the
footer or the shop pages — installing it adds blocks to the website editor and
changes no existing page until one of them is dropped onto a page.
""",
    'version': '19.0.4.0.0',
    'depends': ['website'],
    'data': [
        'views/snippets/s_tecas_hero.xml',
        'views/snippets/s_tecas_engagements.xml',
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
        ],
    },
    'author': 'TECAS',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
