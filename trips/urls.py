from django.urls import path
from . import views

urlpatterns = [
    path('simulate/', views.simulate_trip, name='simulate_trip'),
]