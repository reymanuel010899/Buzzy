from django.core.management.base import BaseCommand
from apps.wallet.models import TokenPackage

class Command(BaseCommand):
    help = 'Seeds the database with default token packages'

    def handle(self, *args, **kwargs):
        packages = [
            {
                'tokens': 100,
                'price': 1.50,
                'is_popular': False,
                'color_gradient': 'from-blue-500 to-cyan-500'
            },
            {
                'tokens': 200,
                'price': 2.90,
                'is_popular': True,
                'color_gradient': 'from-purple-500 to-pink-500'
            },
            {
                'tokens': 500,
                'price': 4.50,
                'is_popular': False,
                'color_gradient': 'from-amber-400 to-orange-600'
            },
            {
                'tokens': 1000,
                'price': 8.00,
                'is_popular': False,
                'color_gradient': 'from-yellow-400 to-yellow-600'
            },
        ]

        for pkg_data in packages:
            pkg, created = TokenPackage.objects.get_or_create(
                tokens=pkg_data['tokens'],
                defaults=pkg_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created package: {pkg.tokens} tokens'))
            else:
                # Update existing packages to match seed data
                for key, value in pkg_data.items():
                    setattr(pkg, key, value)
                pkg.save()
                self.stdout.write(self.style.SUCCESS(f'Successfully updated package: {pkg.tokens} tokens'))

        self.stdout.write(self.style.SUCCESS('Successfully seeded token packages'))
