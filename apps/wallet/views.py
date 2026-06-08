import stripe
from decimal import Decimal
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from apps.wallet.serializers import TransactiosCreateSerializer, TransactionSerializer, WalletSerializer
from apps.wallet.models import WalletModel, TransactionModel
from .models import BankAccount, TokenPackage, GlobalSettings
from .serializers import BankAccountSerializer, TokenPackageSerializer

stripe.api_key = settings.STRIPE_SECRET_KEY

class GetWalletApiVIew(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        wallets = WalletModel.objects.filter(user_id=request.user.id).order_by('id')
        if wallets.exists():
            wallet = wallets.first()
            # Limpiar si hay más de 1 billetera duplicada
            if wallets.count() > 1:
                # Borra todas las adicionales conservando la primera
                WalletModel.objects.filter(id__in=[w.id for w in wallets[1:]]).delete()
        else:
            import uuid
            country_code = request.user.country.code if hasattr(request.user, 'country') and request.user.country else "US"
            wallet = WalletModel.objects.create(
                user=request.user,
                balance=0,
                pass_code=f"{country_code}{str(uuid.uuid4())[:8]}".upper(),
                wallet_type='main'
            )
        serializer = WalletSerializer(wallet)
        gs = GlobalSettings.get_settings()
        data = serializer.data
        data['tokens'] = wallet.tokens
        data['token_value_usd'] = float(gs.custom_token_price_usd)
        data['gift_fee_pct'] = float(gs.gift_fee_pct)
        return Response(data)

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

class VerifyDepositSessionView(APIView):
    def get(self, request, *args, **kwargs):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({'error': 'Missing session_id'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.payment_status == 'paid' or session.status == 'complete':
                metadata = session.metadata
                if metadata and metadata.get('type') == 'wallet_deposit':
                    user_id = metadata.get('user_id')
                    amount = float(metadata.get('amount', 0))
                    
                    if user_id and amount > 0:
                        from django.contrib.auth import get_user_model
                        from apps.wallet.models import WalletModel, TransactionModel
                        from decimal import Decimal
                        User = get_user_model()
                        try:
                            user = User.objects.get(id=user_id)
                            wallet, _ = WalletModel.objects.get_or_create(user=user)
                            
                            # Check if transaction already exists for this session
                            tx_exists = TransactionModel.objects.filter(payment_id=session.id).exists()
                            if not tx_exists:
                                # The 'update_wallet_balance' signal in apps/wallet/models.py 
                                # will automatically add the amount to wallet.balance 
                                # when this TransactionModel is created.
                                
                                # Record transaction
                                TransactionModel.objects.create(
                                    wallet=wallet,
                                    transaction_type='deposit',
                                    status='completed',
                                    amount=Decimal(str(amount)),
                                    description='Deposit via Stripe Checkout',
                                    payment_id=session.id
                                )
                                print(f"Successfully processed deposit for user {user.username}: ${amount}")
                        except Exception as e:
                            print(f"Error processing deposit for {user_id}: {e}")
                            return Response({'error': 'Failed to process deposit internally'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({
                'id': session.id,
                'payment_status': session.payment_status,
                'status': session.status,
                'amount_total': session.amount_total / 100,
                'currency': session.currency,
                'metadata': session.metadata
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WithdrawFundsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        amount = request.data.get('amount')
        bank_account_id = request.data.get('bank_account_id')

        if not amount:
            return Response({'error': 'Amount is required'}, status=400)

        try:
            amount = float(amount)

            if amount <= 0:
                return Response({'error': 'Invalid amount'}, status=400)

            bank_account = BankAccount.objects.get(
                id=bank_account_id,
                user=request.user
            )

            wallet = WalletModel.objects.get(user=request.user)

            if wallet.balance < amount:
                return Response(
                    {'error': 'Saldo insuficiente'},
                    status=400
                )

            decimal_amount = Decimal(str(amount))

            # Stripe amount en centavos
            stripe_amount = int(amount * 100)
            # Crear transferencia en Stripe
            try:
                transfer = stripe.Transfer.create(
                    amount=stripe_amount,
                    currency="usd",
                    destination=bank_account.stripe_account_id,
                    description=f"Withdrawal for {request.user.username}",
                )
            except Exception as e:
                print(e, "=========")
                error_message = str(e)
                clean_message = error_message.split(": ", 1)[1].split(" See:")[0]
                return Response({'active': False,  "charges_enabled": False, "payouts_enabled": False, "message": clean_message}, status=status.HTTP_200_OK)

            # Descontar del wallet
            wallet.balance -= decimal_amount
            wallet.save()

            transaction = TransactionModel.objects.create(
                wallet=wallet,
                transaction_type='withdrawal',
                status='completed',
                amount=decimal_amount,
                bank_account=bank_account,
                payment_id=transfer.id,
                description="Withdrawal via Stripe"
            )

            return Response({
                "message": "Retiro enviado correctamente",
                "stripe_transfer_id": transfer.id,
                "balance": wallet.balance
            })

        except Exception as e:
            return Response({'error': str(e)}, status=400)

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



class BankAccountListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stripe_accounts = BankAccount.objects.filter(user=request.user)
        for stripe_account in stripe_accounts:
            account = stripe.Account.retrieve(stripe_account.stripe_account_id)
            if account.details_submitted and account.payouts_enabled and stripe_account.is_active == False:
                stripe_account.is_active = True
                stripe_account.save()

        serializer = BankAccountSerializer(stripe_accounts.filter(is_active=True), many=True)
        return Response(serializer.data)

    def post(self, request):

        serializer = BankAccountSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            bank_account = serializer.save()

            return Response({
                "bank_account": BankAccountSerializer(bank_account).data,
                "stripe_onboarding_url": getattr(bank_account, "onboarding_url", None)
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BankAccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            account = BankAccount.objects.get(pk=pk, user=request.user)
        except BankAccount.DoesNotExist:
            return Response({'error': 'Cuenta no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        
        # Restriction: Cannot delete the last bank account
        if BankAccount.objects.filter(user=request.user).count() <= 1:
            return Response(
                {'error': 'No puedes eliminar tu única cuenta bancaria. Debes agregar otra primero.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        account.delete()
        
        # If deleted primary, make another one primary
        if account.is_primary:
            next_account = BankAccount.objects.filter(user=request.user).first()
            if next_account:
                next_account.is_primary = True
                next_account.save()
                
        return Response({'message': 'Cuenta bancaria eliminada correctamente'}, status=status.HTTP_200_OK)

class TokenPackageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        packages = TokenPackage.objects.filter(is_active=True)
        serializer = TokenPackageSerializer(packages, many=True)
        return Response(serializer.data)


class CalculateTokenPriceApiView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings = GlobalSettings.get_settings()
        price_per_token = Decimal(str(settings.custom_token_price_usd))

        usd_str = request.query_params.get('usd')
        tokens_str = request.query_params.get('tokens')

        if usd_str:
            try:
                usd_amount = Decimal(usd_str)
                if usd_amount <= 0:
                    raise ValueError
            except (ValueError, Exception):
                return Response({'error': 'Monto inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            tokens_qty = int(usd_amount / price_per_token)
            return Response({
                'usd': round(usd_amount, 2),
                'tokens': tokens_qty,
            }, status=status.HTTP_200_OK)

        if tokens_str:
            try:
                tokens_qty = int(tokens_str)
                if tokens_qty <= 0:
                    raise ValueError
            except ValueError:
                return Response({'error': 'Cantidad inválida.'}, status=status.HTTP_400_BAD_REQUEST)
            total_price = Decimal(str(tokens_qty)) * price_per_token
            return Response({
                'tokens': tokens_qty,
                'total_price': round(total_price, 2)
            }, status=status.HTTP_200_OK)

        return Response({'error': 'Parámetro "usd" o "tokens" requerido.'}, status=status.HTTP_400_BAD_REQUEST)

class ConvertTokensView(APIView):
    """Convierte todos los tokens del usuario a USD en su wallet."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            wallet = WalletModel.objects.get(user=request.user)
        except WalletModel.DoesNotExist:
            return Response({'error': 'Wallet no encontrada'}, status=400)

        if wallet.tokens <= 0:
            return Response({'error': 'No tienes tokens para convertir'}, status=400)

        gs = GlobalSettings.get_settings()
        tokens_to_convert = wallet.tokens
        usd_amount = Decimal(str(tokens_to_convert)) * Decimal(str(gs.custom_token_price_usd))
        usd_amount = usd_amount.quantize(Decimal('0.01'))

        wallet.tokens = 0
        wallet.balance += usd_amount
        wallet.save()

        TransactionModel.objects.create(
            wallet=wallet,
            amount=usd_amount,
            transaction_type='income',
            description=f'Conversión de {tokens_to_convert} tokens a USD',
            status='completed'
        )

        serializer = WalletSerializer(wallet)
        data = serializer.data
        data['tokens'] = wallet.tokens
        data['token_value_usd'] = float(gs.custom_token_price_usd)
        data['gift_fee_pct'] = float(gs.gift_fee_pct)
        return Response({
            'message': f'{tokens_to_convert} tokens convertidos a ${usd_amount} USD',
            'converted_usd': float(usd_amount),
            'wallet': data
        })


class StripeAccountStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        stripe_account = BankAccount.objects.filter(user=user, is_primary=True).first()
        account = stripe.Account.retrieve(stripe_account.stripe_account_id)
        # verificar si terminó onboarding
        if account.details_submitted and account.payouts_enabled:

            stripe_account.is_active = True
            stripe_account.save()

            return Response({
                "active": True,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled
            })

        return Response({
            "active": False,
            "charges_enabled": account.charges_enabled,
            "payouts_enabled": account.payouts_enabled
        })

class TransactionHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = WalletModel.objects.filter(user=request.user).first()
        if not wallet:
            return Response({"results": [], "count": 0})

        # filter: all | income (deposit) | expense (withdrawal, transfer)
        filter_type = request.query_params.get("type", "all")
        qs = TransactionModel.objects.filter(wallet=wallet).order_by('-created_at')

        if filter_type == "income":
            qs = qs.filter(transaction_type='deposit')
        elif filter_type == "expense":
            qs = qs.filter(transaction_type__in=['withdrawal', 'transfer'])

        # simple pagination: page_size=20
        page_size = int(request.query_params.get("page_size", 20))
        page = int(request.query_params.get("page", 1))
        start = (page - 1) * page_size
        end = start + page_size
        total = qs.count()
        serializer = TransactionSerializer(qs[start:end], many=True)
        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "has_next": end < total,
            "results": serializer.data,
        })
