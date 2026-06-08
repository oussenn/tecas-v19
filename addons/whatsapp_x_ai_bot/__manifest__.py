{
    'name': 'WhatsApp AI Bot',
    'version': '19.0.1.0.0',
    'summary': 'AI-powered WhatsApp onboarding assistant for incoming leads',
    'description': (
        'AI assistant that qualifies incoming WhatsApp leads '
        'via a configurable menu flow and escalates to a salesman when ready.'
    ),
    'author': 'Oussama Ennaciri',
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
