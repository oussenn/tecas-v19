# -*- coding: utf-8 -*-
{
    'name': "smfourniture_extention",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "`ayadbrahim5@gmail.com`",
    'website': "https://www.linkedin.com/in/brahim-ayad-826a26a3/",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'sale', 'purchase'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'report/sale_order_duplicated.xml',
        'report/report_sale_order_to_invoice.xml',
        'report/report_purchase_order_to_invoice.xml',
        'report/action_sale_order_duplicated.xml',
        'views/sale_order.xml',
        'views/purchase_order.xml',
    ],
}

