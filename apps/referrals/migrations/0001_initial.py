import apps.referrals.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReferralProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_invitados', models.PositiveIntegerField(default=0, verbose_name='Total de invitados exitosos')),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_profile',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Perfil de Referido',
                'verbose_name_plural': 'Perfiles de Referidos',
            },
        ),
        migrations.CreateModel(
            name='ReferralToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(
                    default=apps.referrals.models._generate_token,
                    max_length=64,
                    unique=True,
                    verbose_name='Token único',
                )),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='Activo')),
                ('expires_at', models.DateTimeField(
                    db_index=True,
                    default=apps.referrals.models._default_expires_at,
                    verbose_name='Expira en',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='referral_tokens',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Dueño del link',
                )),
                ('used_by', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='used_referral_token',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Usado por',
                )),
            ],
            options={
                'verbose_name': 'Token de Referido',
                'verbose_name_plural': 'Tokens de Referidos',
            },
        ),
        migrations.AddIndex(
            model_name='referraltoken',
            index=models.Index(fields=['token', 'is_active'], name='referrals_r_token_is_active_idx'),
        ),
    ]
