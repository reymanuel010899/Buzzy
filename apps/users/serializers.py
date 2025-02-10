from rest_framework import serializers

class LoginZerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    access_token = serializers.CharField()
    

    # def validate(self, attrs):
    #     username = attrs.get('username')
    #     password = attrs.get('password')

        # if username and password:
        #     user = authenticate(request=self.context.get('request'),
        #                         username=username, password=password)

        #     # The authenticate call simply returns None for is_active=False
        #     # users. (Assuming the default ModelBackend authentication
        #     # backend.)
        #     if not user:
        #         msg = ('Unable to log in with provided credentials.')
        #         raise serializers.ValidationError(msg, code='authorization')
        # else:
        #     msg = ('Must include "username" and "password".')
        #     raise serializers.ValidationError(msg, code='authorization')

        # attrs['user'] = user
        # return attrs