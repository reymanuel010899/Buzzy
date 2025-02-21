from django.db import models
from apps.users.models import User
# Create your models here.

class WalletModel(models.Model):
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.IntegerField()
    pass_code = models.CharField(max_length=5)

    def __str__(self):
        return f"wallet {self.id} - {self.amount}"

    class Meta:
        verbose_name = 'wallet'
        verbose_name_plural = 'wallets'
