from django.core.management.base import BaseCommand
from django.db import connection
from apps.users.models import Country


COUNTRIES = [
    ("Afghanistan", "AF"), ("Albania", "AL"), ("Algeria", "DZ"),
    ("Andorra", "AD"), ("Angola", "AO"), ("Argentina", "AR"),
    ("Armenia", "AM"), ("Australia", "AU"), ("Austria", "AT"),
    ("Azerbaijan", "AZ"), ("Bahamas", "BS"), ("Bahrain", "BH"),
    ("Bangladesh", "BD"), ("Belarus", "BY"), ("Belgium", "BE"),
    ("Belize", "BZ"), ("Benin", "BJ"), ("Bolivia", "BO"),
    ("Bosnia and Herzegovina", "BA"), ("Botswana", "BW"),
    ("Brazil", "BR"), ("Brunei", "BN"), ("Bulgaria", "BG"),
    ("Burkina Faso", "BF"), ("Cambodia", "KH"), ("Cameroon", "CM"),
    ("Canada", "CA"), ("Chile", "CL"), ("China", "CN"),
    ("Colombia", "CO"), ("Costa Rica", "CR"), ("Croatia", "HR"),
    ("Cuba", "CU"), ("Cyprus", "CY"), ("Czech Republic", "CZ"),
    ("Denmark", "DK"), ("Dominican Republic", "DO"), ("Ecuador", "EC"),
    ("Egypt", "EG"), ("El Salvador", "SV"), ("Estonia", "EE"),
    ("Ethiopia", "ET"), ("Finland", "FI"), ("France", "FR"),
    ("Georgia", "GE"), ("Germany", "DE"), ("Ghana", "GH"),
    ("Greece", "GR"), ("Guatemala", "GT"), ("Haiti", "HT"),
    ("Honduras", "HN"), ("Hungary", "HU"), ("Iceland", "IS"),
    ("India", "IN"), ("Indonesia", "ID"), ("Iran", "IR"),
    ("Iraq", "IQ"), ("Ireland", "IE"), ("Israel", "IL"),
    ("Italy", "IT"), ("Jamaica", "JM"), ("Japan", "JP"),
    ("Jordan", "JO"), ("Kazakhstan", "KZ"), ("Kenya", "KE"),
    ("Kuwait", "KW"), ("Latvia", "LV"), ("Lebanon", "LB"),
    ("Libya", "LY"), ("Lithuania", "LT"), ("Luxembourg", "LU"),
    ("Malaysia", "MY"), ("Maldives", "MV"), ("Mali", "ML"),
    ("Malta", "MT"), ("Mexico", "MX"), ("Moldova", "MD"),
    ("Monaco", "MC"), ("Mongolia", "MN"), ("Montenegro", "ME"),
    ("Morocco", "MA"), ("Mozambique", "MZ"), ("Myanmar", "MM"),
    ("Namibia", "NA"), ("Nepal", "NP"), ("Netherlands", "NL"),
    ("New Zealand", "NZ"), ("Nicaragua", "NI"), ("Nigeria", "NG"),
    ("North Korea", "KP"), ("Norway", "NO"), ("Oman", "OM"),
    ("Pakistan", "PK"), ("Panama", "PA"), ("Paraguay", "PY"),
    ("Peru", "PE"), ("Philippines", "PH"), ("Poland", "PL"),
    ("Portugal", "PT"), ("Puerto Rico", "PR"), ("Qatar", "QA"),
    ("Romania", "RO"), ("Russia", "RU"), ("Rwanda", "RW"),
    ("Saudi Arabia", "SA"), ("Senegal", "SN"), ("Serbia", "RS"),
    ("Singapore", "SG"), ("Slovakia", "SK"), ("Slovenia", "SI"),
    ("Somalia", "SO"), ("South Africa", "ZA"), ("South Korea", "KR"),
    ("Spain", "ES"), ("Sri Lanka", "LK"), ("Sudan", "SD"),
    ("Sweden", "SE"), ("Switzerland", "CH"), ("Syria", "SY"),
    ("Taiwan", "TW"), ("Tanzania", "TZ"), ("Thailand", "TH"),
    ("Tunisia", "TN"), ("Turkey", "TR"), ("Uganda", "UG"),
    ("Ukraine", "UA"), ("United Arab Emirates", "AE"),
    ("United Kingdom", "GB"), ("United States", "US"),
    ("Uruguay", "UY"), ("Uzbekistan", "UZ"), ("Venezuela", "VE"),
    ("Vietnam", "VN"), ("Yemen", "YE"), ("Zambia", "ZM"),
    ("Zimbabwe", "ZW"),
]


class Command(BaseCommand):
    help = "Seed all countries into the Country model and reset the PK sequence"

    def handle(self, *args, **options):
        created = 0
        updated = 0

        # Fix the broken sequence FIRST so inserts don't collide on id
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('users_country', 'id'), "
                "COALESCE((SELECT MAX(id) FROM users_country), 0) + 1, false);"
            )
            self.stdout.write("Sequence reset. Inserting countries...")

        for name, code in COUNTRIES:
            obj, was_created = Country.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        # Final sequence reset to MAX(id) after all inserts
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('users_country', 'id'), "
                "(SELECT MAX(id) FROM users_country));"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {created} created, {updated} updated. "
                f"Total countries: {Country.objects.count()}. "
                f"PK sequence reset."
            )
        )
