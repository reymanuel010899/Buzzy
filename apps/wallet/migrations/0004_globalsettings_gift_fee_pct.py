from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0003_add_monetizable_view_log_and_snapshot_total'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalsettings',
            name='gift_fee_pct',
            field=models.DecimalField(
                decimal_places=2,
                default=30.0,
                help_text='Porcentaje que se queda la plataforma de cada regalo (ej. 30 = 30%).',
                max_digits=5,
            ),
        ),
    ]
