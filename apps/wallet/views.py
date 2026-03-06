import stripe
from decimal import Decimal
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from apps.wallet.serializers import TransactiosCreateSerializer, WalletSerializer
from apps.wallet.models import WalletModel, TransactionModel

stripe.api_key = settings.STRIPE_SECRET_KEY

class GetWalletApiVIew(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        wallet = WalletModel.objects.get(user_id=request.user.id)
        serializer = WalletSerializer(wallet)
        return Response(serializer.data)

class CreateDepositSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        amount = request.data.get('amount')
        if not amount:
            return Response({'error': 'Amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = float(amount)
            if amount < 1.0: # Stripe minimum is usually around 50 cents, but 1 USD is safer
                return Response({'error': 'Minimum deposit is $1.00'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Create Stripe Checkout Session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {
                                'name': "Buzzy Wallet Deposit",
                                'description': f"Deposit to user {request.user.username}'s wallet",
                            },
                            'unit_amount': int(amount * 100),
                        },
                        'quantity': 1,
                    },
                ],
                mode='payment',
                success_url=settings.FRONTEND_URL + '/wallet-success?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=settings.FRONTEND_URL + '/wallet-cancel',
                client_reference_id=str(request.user.id),
                metadata={
                    'type': 'wallet_deposit',
                    'user_id': request.user.id,
                    'amount': amount
                }
            )

            return Response({'url': checkout_session.url})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WithdrawFundsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        amount = request.data.get('amount')
        if not amount:
            return Response({'error': 'Amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount = float(amount)
            if amount <= 0:
                return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)
            
            wallet = WalletModel.objects.get(user=request.user)
            if wallet.balance < amount:
                return Response({'error': 'Insufficient funds'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Create a PENDING withdrawal transaction
            # Balance is NOT deducted yet by the signal because status is 'pending'
            # However, for withdrawals, we might want to "lock" the balance or deduct it immediately
            # Based on user request "que pueda retirar fondo de mi app", usually we deduct immediately to prevent double-spending
            
            # Let's deduct immediately for withdrawals to be safe
            wallet.balance -= amount
            wallet.save()

            TransactionModel.objects.create(
                wallet=wallet,
                transaction_type='withdrawal',
                status='pending',
                amount=amount,
                description=f"Solicitud de retiro de fondos"
            )

            return Response({'message': 'Solicitud de retiro enviada correctamente', 'balance': wallet.balance})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CreateTransationsApiView(APIView):
    serializer_class=TransactiosCreateSerializer
    permission_classes = [IsAuthenticated]
    def post(self, request):
        validate_data = self.serializer_class(data=self.request.data)
        if validate_data.is_valid():
            wallet_by_user = WalletModel.objects.get(user=request.user)
            validate_data.save(wallet=wallet_by_user)
            return Response(
                {"message": "Transacción creada correctamente", "data": validate_data.data},
                status=status.HTTP_201_CREATED
            )

        return Response(
            validate_data.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

class BuyTokensApiView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        tokens_to_buy = request.data.get('tokens')
        cost = request.data.get('cost')
        
        if not tokens_to_buy or not cost:
            return Response(
                {"error": "Se requieren los campos 'tokens' y 'cost'"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            tokens_to_buy = int(tokens_to_buy)
            cost = Decimal(str(cost))
        except ValueError:
            return Response(
                {"error": "Tipos de datos inválidos para 'tokens' o 'cost'"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if tokens_to_buy <= 0 or cost < 0:
            return Response(
                {"error": "Cantidad o costo inválidos"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        wallet = WalletModel.objects.get(user=request.user)
        
        if wallet.balance < cost:
            return Response(
                {"error": "Saldo insuficiente en dólares para comprar estos tokens"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Deduct balance and add tokens
        wallet.balance -= cost
        wallet.tokens += tokens_to_buy
        wallet.save()
        
        # Optionally create a TransactionModel record for the purchase
        from apps.wallet.models import TransactionModel
        TransactionModel.objects.create(
            wallet=wallet,
            transaction_type='transfer',
            status='completed',
            amount=cost,
            description=f"Compra de {tokens_to_buy} tokens"
        )
        
        serializer = WalletSerializer(wallet)
        return Response({
            "message": f"Compra de {tokens_to_buy} tokens exitosa",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

