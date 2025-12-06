from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from apps.wallet.serializers import TransactiosCreateSerializer, WalletSerializer
from apps.wallet.models import WalletModel
# Create your views here.

    
class GetWalletApiVIew(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        wallet = WalletModel.objects.get(user_id=request.user.id)
        serializer = WalletSerializer(wallet)
        return Response(serializer.data)
    
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

