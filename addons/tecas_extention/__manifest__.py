# -*- coding: utf-8 -*-
{
    'name': "tecas_extention",
    'summary': "Tecas Invoice Extensions",
    'author': "Oussama Ennaciri",
    'category': 'account',
    'version': '19.0.0.1',
    'depends': ['base', 'account', 'sale'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'report/invoice_inherited.xml',
        'report/report_layout_inherited.xml',
        'views/account_move.xml',
        'wizard/split_invoice.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tecas_extention/static/src/js/array_polyfill.js',
            'tecas_extention/static/src/css/statusbar_fix.css',
            'tecas_extention/static/src/js/account_move_rpc.js',
            'tecas_extention/static/src/js/editor_destroy_patch.js',
        ],
    },
    'license': 'LGPL-3',
}
