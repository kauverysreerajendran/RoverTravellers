from django.contrib.auth import authenticate, login, logout
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Role, User
from .serializers import RoleSerializer, UserSerializer


class ApiLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        return Response(UserSerializer(user).data)


class ApiLogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


class CurrentUserView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all().order_by("username")
    serializer_class = UserSerializer
    search_fields = ["username", "first_name", "last_name", "email"]
    filterset_fields = ["is_active", "is_active_employee"]
    ordering_fields = ["username", "date_joined"]


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    search_fields = ["code", "name"]
