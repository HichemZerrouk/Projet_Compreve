from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.login_view, name='login'),
    path('fichiers/', views.fichiers_view, name='fichiers'),
    path('bases_de_donnees/', views.bases_de_donnees_view, name='bases_de_donnees'),
    path('upload_json/', views.upload_json, name='upload_json'),

    path('recherche/', views.recherche_view, name='recherche'),

    path('delete-filename/', views.delete_filename, name="delete-filename"),

    path('export_filtered_json/' , views.export_filtered_json, name='export_filtered_json'),

    path('export_filtered_csv/', views.export_filtered_csv, name='export_filtered_json'),

    path('export_filtered_xml/', views.export_filtered_xml, name='export_filtered_xml'),

    path('export_global_filtered_json/', views.export_global_filtered_json, name='export_global_filtered_json'),

    path('export_global_filtered_xml/', views.export_global_filtered_xml, name='export_global_filtered_xml'),

    path('export_global_filtered_csv/', views.export_global_filtered_csv, name='export_global_filtered_csv'),


]
