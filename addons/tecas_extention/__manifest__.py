# -*- coding: utf-8 -*-
{
    'name': "tecas_extention",
    'summary': "Tecas Invoice Extensions",
    'author': "@brahimayad",
    'website': "ayadbrahim5@gmail.com",
    'category': 'account',
    'version': '19.0.0.1',
    'depends': ['base', 'account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'report/invoice_inherited.xml',
        'views/account_move.xml',
        'wizard/split_invoice.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tecas_extention/static/src/js/account_move_rpc.js',
        ],
    },
    'license': 'LGPL-3',
}
