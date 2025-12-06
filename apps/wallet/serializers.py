from rest_framework.serializers import ModelSerializer

from apps.videos.serializers import UserSerializers
from apps.wallet.models import TransactionModel, WalletModel

class WalletSerializer(ModelSerializer):
    user= UserSerializers()
    class Meta:
        model=WalletModel
        fields=('balance', 'user', 'pass_code', 'wallet_type')


class TransactiosCreateSerializer(ModelSerializer):
    class Meta:
        model=TransactionModel
        fields=('transaction_type', 'amount', 'description')
