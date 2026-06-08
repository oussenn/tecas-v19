{
    'name': 'TECAS WhatsApp AI',
    'version': '19.0.1.0.0',
    'summary': 'AI-powered WhatsApp onboarding for incoming leads',
    'description': (
        'AI assistant that qualifies incoming WhatsApp leads '
        'on the Service Commercial number and escalates to a salesman when ready.'
    ),
    'author': 'TECAS ENERGIE SOLAIRE',
    'website': 'https://tecas.ma',
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'whatsapp',
        'crm',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/automation.xml',
        'views/whatsapp_ai_config_views.xml',
        'views/whatsapp_ai_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
