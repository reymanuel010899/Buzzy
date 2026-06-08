import stripe
from rest_framework import serializers
from .models import WalletModel, TransactionModel, BankAccount, TokenPackage
from .utils import encrypt_data
from django.conf import settings
from apps.videos.serializers import UserSerializers
stripe.api_key = settings.STRIPE_SECRET_KEY

class WalletSerializer(serializers.ModelSerializer):
    user= UserSerializers()
    class Meta:
        model=WalletModel
        fields='__all__'

class BankAccountSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(write_only=True)
    routing_number = serializers.CharField(write_only=True, required=False, allow_blank=True)
    masked_number = serializers.CharField(source='masked_account_number', read_only=True)

    class Meta:
        model = BankAccount
        fields = ['id', 'account_holder_name', 'bank_name', 'account_number', 'routing_number', 'masked_number', 'is_primary', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user

        account_number = validated_data.pop('account_number')
        routing_number = validated_data.pop('routing_number', "")

        validated_data['encrypted_account_number'] = encrypt_data(account_number)
        validated_data['encrypted_routing_number'] = encrypt_data(routing_number)

        # crear cuenta stripe connect
        stripe_account = stripe.Account.create(
            type="express",
            email=user.email,
            country="US",
        )

        validated_data['stripe_account_id'] = stripe_account.id

        # primera cuenta = primaria
        if not BankAccount.objects.filter(user=user).exists():
            validated_data['is_primary'] = True

        bank_account = BankAccount.objects.create(
            user=user,
            **validated_data
        )

        # crear onboarding link para que agregue su banco
        account_link = stripe.AccountLink.create(
            account=stripe_account.id,
            refresh_url=settings.FRONTEND_URL.rstrip('/') + '/wallet',
            return_url=settings.FRONTEND_URL.rstrip('/') + '/wallet-success',
            type="account_onboarding",
        )

        bank_account.onboarding_url = account_link.url  # temporal

        return bank_account


class TransactiosCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model=TransactionModel
        fields=('transaction_type', 'amount', 'description')

class TokenPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenPackage
        fields = ['id', 'tokens', 'price', 'is_popular', 'color_gradient']


class TransactionSerializer(serializers.ModelSerializer):
    """Read-only serializer for transaction history."""
    direction = serializers.SerializerMethodField()
    display_description = serializers.SerializerMethodField()

    class Meta:
        model = TransactionModel
        fields = [
            'id', 'transaction_type', 'status', 'amount',
            'description', 'payment_id', 'direction',
            'display_description', 'created_at',
        ]

    def get_direction(self, obj) -> str:
        """income for deposits, expense for withdrawals/transfers."""
        if obj.transaction_type == 'deposit':
            return 'income'
        return 'expense'

    def get_display_description(self, obj) -> str:
        if obj.description:
            return obj.description
        labels = {
            'deposit':    'Depósito recibido',
            'withdrawal': 'Retiro de fondos',
            'transfer':   'Transferencia de tokens',
        }
        return labels.get(obj.transaction_type, obj.transaction_type.capitalize())
