from rest_framework import serializers
from .models import WalletModel, TransactionModel, BankAccount
from .utils import encrypt_data

from apps.videos.serializers import UserSerializers

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
        account_number = validated_data.pop('account_number')
        routing_number = validated_data.pop('routing_number', "")
        
        validated_data['encrypted_account_number'] = encrypt_data(account_number)
        validated_data['encrypted_routing_number'] = encrypt_data(routing_number)
        
        # If this is the first bank account, make it primary
        if not BankAccount.objects.filter(user=self.context['request'].user).exists():
            validated_data['is_primary'] = True
            
        return super().create(validated_data)


class TransactiosCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model=TransactionModel
        fields=('transaction_type', 'amount', 'description')
