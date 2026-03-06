import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Buzzy.settings')
django.setup()

from apps.subscriptions.models import SubscriptionPlan

def seed_plans():
    plans = [
        {
            'name': 'VIP',
            'description': 'Borde dorado en comentarios (30/mes), contenido detrás de cámaras, regalos exclusivos.',
            'price': 9.99,
        },
        {
            'name': 'PLUS',
            'description': '3 llamadas obligatorias al mes, todas las ventajas VIP, borde azul en comentarios.',
            'price': 24.99,
        },
        {
            'name': 'FRIEND',
            'description': '10 llamadas obligatorias al mes, todas las ventajas VIP y PLUS.',
            'price': 49.99,
        },
    ]

    for plan_data in plans:
        plan, created = SubscriptionPlan.objects.get_or_create(
            name=plan_data['name'],
            defaults={
                'description': plan_data['description'],
                'price': plan_data['price'],
            }
        )
        if not created:
            plan.description = plan_data['description']
            plan.price = plan_data['price']
            plan.save()
            print(f"Updated plan: {plan.name}")
        else:
            print(f"Created plan: {plan.name}")

if __name__ == '__main__':
    seed_plans()
