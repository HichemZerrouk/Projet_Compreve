from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.db.models import Q
from .models import TwitchMessage, StreamInfo, ViewerCount, UploadedFile
import os
import json
import csv
import xml.etree.ElementTree as ET
from datetime import datetime
from django.conf import settings
from math import ceil
import shutil
from xml.dom import minidom
import io
from django.utils.timezone import make_aware
from django.db import connection  # Direct database connection
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Lower
from django.db.models import IntegerField, Value, Case, When
from django.db.models.functions import Cast
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.db.models import Q, Case, When, Value, IntegerField
from django.db import IntegrityError
from django.db import transaction
from itertools import chain
import ast  # Safely parse the string list into Python lists
from django.db.models import OuterRef, Subquery
import xml.etree.ElementTree as ET
import logging


def login_view(request):
    return render(request, 'login.html')



"""
    Vue Django pour gérer l'affichage des fichiers téléchargés.
    Cette vue permet de récupérer les noms de fichiers uniques, de filtrer les résultats en fonction d'une requête de recherche,
    de paginer les résultats, et de renvoyer les données sous forme de JSON pour les requêtes AJAX ou de rendre un template pour les requêtes normales.
"""
def fichiers_view(request):
    # Récupérer les noms de fichiers uniques depuis la base de données.
    # distinct garantit que chaque nom de fichier est unique.
    files = UploadedFile.objects.values_list('filename', flat=True).distinct()

    # Gérer le filtrage par recherche
    # Récupérer la requête de recherche depuis les paramètres GET de la requête.
    search_query = request.GET.get('search', '').strip()
    if search_query:
        # Si une requête de recherche est présente, filtrer les fichiers dont le nom contient la requête.
        # '__icontains' permet une recherche insensible à la casse.
        files = UploadedFile.objects.filter(filename__icontains=search_query).values_list('filename', flat=True)

    # Pagination des résultats
    # Créer un objet Paginator pour paginer les résultats, affichant 15 fichiers par page.
    paginator = Paginator(files, 15)
    # Récupérer le numéro de page depuis les paramètres GET de la requête, par défaut 1.
    page_number = request.GET.get('page', 1)

    # Obtenir l'objet Page pour la page actuelle.
    page_obj = paginator.get_page(page_number)


    # Vérifier si la requête est une requête AJAX
    # Si l'en-tête 'X-Requested-With' est défini sur 'XMLHttpRequest', cela signifie que la requête est une requête AJAX.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Retourner une réponse JSON contenant les fichiers de la page actuelle, le nombre total de pages, et le numéro de la page actuelle.
        return JsonResponse({
            'files': [{'name': filename} for filename in page_obj],
            'total_pages': paginator.num_pages,
            'current_page': page_obj.number
        })

    # Rendre le template 'fichiers.html' pour les requêtes normales (non-AJAX)
    # Passer les fichiers de la page actuelle, le nombre total de pages, et le numéro de la page actuelle au contexte du template.
    return render(request, 'fichiers.html', {
        'files': [{'name': filename} for filename in page_obj],
        'total_pages': paginator.num_pages,
        'current_page': page_obj.number
    })



"""
    Vue Django pour gérer le téléversement des fichiers JSON vers la BDD.
    Cette vue permet de recevoir des fichiers JSON via une requête POST, de les valider,
    et de stocker les données contenues dans ces fichiers dans la base de données.
"""

def upload_json(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'})

    if 'files' not in request.FILES:
        return JsonResponse({'success': False, 'erreur': 'aucun fichier uploadé'})

    # Récupérer la liste des fichiers téléchargés
    uploaded_files = request.FILES.getlist('files')
    results = {"success": [], "failed": []}

    # Parcourir chaque fichier téléchargé
    for uploaded_file in uploaded_files:
        file_name = uploaded_file.name
        # Vérifier que le fichier a une extension .json
        if not file_name.endswith('.json'):
            results["failed"].append({"file": file_name, "error": "File must be a JSON file"})
            continue

        try:
            file_content = uploaded_file.read().decode('utf-8')
            data = json.loads(file_content)
            # Utiliser une transaction atomique pour garantir que toutes les opérations de base de données réussissent ou échouent ensemble
            with transaction.atomic():
                uploaded_file_obj, created = UploadedFile.objects.get_or_create(filename=file_name)

                # Initialiser des listes pour stocker les objets à créer dans la base de données
                messages = []
                stream_infos = []
                viewer_counts = []
                valid_sanctions = {"Deleted", "Timeout", "Ban", None}

                # Parcourir les données de streaminfo dans le fichier JSON
                for stream in data.get('streaminfos', []):
                    stream_info = StreamInfo(
                        uploaded_file=uploaded_file_obj,
                        channel=stream.get("channel", ""),
                        title=stream.get("title", ""),
                        category=stream.get("category", ""),
                        language=stream.get("language", ""),
                        is_mature=bool(stream.get("isMature", False)),
                        uptime=stream.get("uptime", ""),
                        start_time=stream.get("startTime", ""),
                        timestamp=stream.get("timestamp", "")
                    )
                    stream_infos.append(stream_info)

                # Vérifier qu'il y a au moins une entrée de streaminfo
                if not stream_infos:
                    raise ValueError("Ce fichier ne peut pas être uploadé car il ne contient pas (streaminfos)")

                StreamInfo.objects.bulk_create(stream_infos)

                for msg in data.get('allMessages', []):
                    if not msg.get('messageId'):
                        continue

                # Créer un objet TwitchMessage pour chaque entrée de message
                    messages.append(TwitchMessage(
                        uploaded_file=uploaded_file_obj,
                        message=msg.get('message', ''),
                        user=msg.get('user', ''),
                        message_id=msg.get('messageId', ''),
                        timestamp=msg.get('timestamp', ''),
                        uptime=msg.get('uptime', ''),
                        status=msg.get('status', []) if isinstance(msg.get('status', []), list) else [],
                        is_moderated=msg.get('isModerated', False),
                        sanction=msg.get('sanction', None) if msg.get('sanction', None) in valid_sanctions else None,
                        duration=msg.get('duration', None),
                        moderation_uptime=msg.get('moderation_uptime', ''),
                        moderation_starttime=msg.get('moderation_starttime', '')
                    ))


                # Parcourir les données de comptage de spectateurs dans le fichier JSON
                for viewer in data.get('viewercount', []):
                    viewer_counts.append(ViewerCount(
                        uploaded_file=uploaded_file_obj,
                        viewer_count=viewer.get('viewerCount', 0),
                        uptime=viewer.get('uptime', ''),
                        timestamp=viewer.get('timestamp', '')
                    ))

            # Créer les objets TwitchMessage et ViewerCount dans la base de données en une seule opération
                if messages:
                    TwitchMessage.objects.bulk_create(messages)
                if viewer_counts:
                    ViewerCount.objects.bulk_create(viewer_counts)

            # Ajouter le nom du fichier aux résultats réussis
            results["success"].append(file_name)

        except json.JSONDecodeError:
            results["failed"].append({"file": file_name, "error": "Format JSON Invalide"})
        except IntegrityError:
            results["failed"].append({"file": file_name, "error": "Ce fichier existe déja dans la base de données."})
        except Exception as e:
            results["failed"].append({"file": file_name, "error": str(e)})

    # Renvoyer les résultats sous forme de réponse JSON
    return JsonResponse(results)


"""
    Évalue en toute sécurité les chaînes de caractères ressemblant à du JSON en listes Python.
    Cette fonction est utilisée pour convertir une chaîne représentant une liste en une véritable liste Python.
"""
def safe_eval(value):

    if isinstance(value, list):
        return value

    if isinstance(value, str) and value.startswith("["):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return [value]

    return [value]



def get_request_param(request, param_name, default_value=None):
    """Récupère un paramètre de la requête GET ou renvoie une valeur par défaut."""
    return request.GET.get(param_name, default_value)

def get_common_request_params(request):
    """Récupère les paramètres communs à toutes les vues."""
    return {
        'file': get_request_param(request, "file"),
        'searchMessage': get_request_param(request, "searchMessage", ""),
        'searchUser': get_request_param(request, "searchUser", ""),
        'sort': get_request_param(request, "sort", "-timestamp"),
        'page': int(get_request_param(request, "page", 1)),
        'selected_channels' : request.GET.getlist("channels"),
        'filters': json.loads(get_request_param(request, "filters", "{}"))
    }



"""
    Vue Django pour gérer l'affichage et le filtrage des messages Twitch stockés dans la base de données.
    Cette vue permet de récupérer les messages associés à un fichier spécifique, d'appliquer divers filtres,
    de trier les résultats, et de paginer les données pour une navigation efficace. Elle peut renvoyer les données
    sous forme de JSON pour les requêtes AJAX ou rendre un template HTML pour les requêtes normales.
"""

def bases_de_donnees_view(request):
    query_params = get_common_request_params(request)
    # Définir le nombre de messages à afficher par page
    per_page = 50

    try:
        filters = query_params['filters'] if query_params['filters'] else {}
    except json.JSONDecodeError:
        filters = {}

    if not query_params['file']:
        return redirect('fichiers')

    # Filtrer les messages Twitch associés au fichier spécifié
    messages = TwitchMessage.objects.filter(uploaded_file__filename=query_params['file'])

    # Appliquer les filtres basés sur les paramètres de la requête
    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        # Filtrer les messages en fonction de leur état de suppression
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        # Filtrer les messages en fonction de leur statut
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')


    if query_params['searchMessage']:
        # Filtrer les messages dont le contenu correspond à la recherche ( par message)
        messages = messages.filter(message__icontains=query_params['searchMessage'])

    if query_params['searchUser']:
        # Filtrer les messages dont le contenu correspond à la recherche (par utilisateur)
        messages = messages.filter(user__icontains=query_params['searchUser'])


    sort_by = query_params['sort']
    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = '-timestamp'

    if sort_field == "duration":
        # Si le tri est basé sur la durée, annoter les messages avec une valeur numérique pour la durée
        messages = messages.annotate(
            duration_int=Case(
                #attribue une valeur de 9999999 a lifetime afin de garantie sa position dans le tri
                When(duration="lifetime", then=Value(9999999)),
                default=Cast('duration', IntegerField()),
                output_field=IntegerField(),
            )
        ).order_by('-duration_int' if sort_by.startswith('-') else 'duration_int')
    else:
        messages = messages.order_by(sort_by)

    # Pagination des résultats
    paginator = Paginator(messages, per_page)
    messages_page = paginator.get_page(query_params['page'])


    all_statuses = TwitchMessage.objects.values_list("status", flat=True)


    flat_statuses = set(chain.from_iterable(safe_eval(status) for status in all_statuses if status))


    unique_statuses = sorted(flat_statuses)

    # Vérifier si la requête est une requête AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'messages': list(messages_page.object_list.values(
                'id', 'message', 'user', 'message_id', 'uptime', 'timestamp', 'status',
                'uploaded_file__filename', 'is_moderated', 'sanction', 'duration'
            )),
            'total_pages': paginator.num_pages,
            'has_previous': messages_page.has_previous(),
            'has_next': messages_page.has_next(),
            'all_statuses': list(unique_statuses)
        })
    # Rendre le template HTML pour les requêtes normales
    return render(request, 'bases_de_données.html', {
        'messages': messages_page,
        'filename': query_params['file'],
        'searchMessage': query_params['searchMessage'],
        'searchUser': query_params['searchUser'],
        'sort_by': sort_by,
        'current_page': query_params['page'],
        'total_pages': paginator.num_pages,
        'has_previous': messages_page.has_previous(),
        'has_next': messages_page.has_next(),
        'all_statuses': unique_statuses
    })


"""
    Vue Django pour gérer la recherche et l'affichage des messages Twitch avec divers filtres et options de tri.
    Cette vue permet aux utilisateurs de rechercher des messages en fonction de plusieurs critères, de les trier,
    et de les paginer pour une navigation efficace. Elle peut renvoyer les données sous forme de JSON pour les requêtes AJAX
    ou rendre un template HTML pour les requêtes normales. Elle fournit également des statistiques sur les messages.
"""

def recherche_view(request):

    query_params = get_common_request_params(request)
    # Définir le nombre de messages à afficher par page
    per_page = 50

    # Gestion des filtres
    try:
        filters = query_params['filters'] if query_params['filters'] else {}
    except json.JSONDecodeError:
        filters = {}


    streaminfo_subquery = StreamInfo.objects.filter(
        uploaded_file=OuterRef('uploaded_file')
    ).values('channel')[:1]

    messages = TwitchMessage.objects.annotate(
        channel=Subquery(streaminfo_subquery)
    )

    # Appliquer le filtrage par chaîne (si des cases à cocher sont sélectionnées)
    if query_params['selected_channels']:
        messages = messages.filter(channel__in=query_params['selected_channels'])

    # Appliquer les filtres basés sur les paramètres de la requête
    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        # Filtrer les messages en fonction de leur état de suppression
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')


    # Appliquer les requêtes de recherche séparées
    if query_params['searchMessage']:
        messages = messages.filter(message__icontains=query_params['searchMessage'])

    # Filtrer les messages envoyés par un utilisateur spécifique
    if query_params['searchUser']:
        messages = messages.filter(user__icontains=query_params['searchUser'])


    sort_by = query_params['sort']
    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status','moderation_starttime','moderation_uptime', 'channel']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = '-timestamp'

    if sort_field == "duration":
        messages = messages.annotate(
            duration_int=Case(
                When(duration="lifetime", then=Value(9999999)),
                default=Cast('duration', IntegerField()),
                output_field=IntegerField(),
            )
        ).order_by('-duration_int' if sort_by.startswith('-') else 'duration_int')
    else:
        messages = messages.order_by(sort_by)


    paginator = Paginator(messages, per_page)
    messages_page = paginator.get_page(query_params['page'])


    all_statuses = TwitchMessage.objects.values_list("status", flat=True)

    mod_startime = TwitchMessage.objects.values_list("moderation_starttime", flat=True)
    mod_uptime = TwitchMessage.objects.values_list("moderation_uptime", flat=True)
    print("mod_starttime =", mod_startime)


    flat_statuses = set(chain.from_iterable(safe_eval(status) for status in all_statuses if status))


    unique_statuses = sorted(flat_statuses)

    # Calcul des statistiques
    total_messages = TwitchMessage.objects.count()
    deleted_messages = messages.filter(sanction="Deleted").count()
    total_users = messages.values("user").distinct().count()
    total_channels = StreamInfo.objects.values("channel").distinct().count()
    total_streams = TwitchMessage.objects.values("uploaded_file").distinct().count()

    # Vérifier si la requête est une requête AJAX
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "messages": list(messages_page.object_list.values(
                "id", "message", "user", "timestamp", "uptime", "is_moderated", "sanction", "duration","moderation_starttime", "moderation_uptime", "status", "channel"
            )),
            "total_pages": paginator.num_pages,
            "current_page": messages_page.number,
            "has_previous": messages_page.has_previous(),
            "has_next": messages_page.has_next(),
            "all_statuses": list(unique_statuses),
            "stats": {
                "total_messages": total_messages,
                "deleted_messages": deleted_messages,
                "total_users": total_users,
                "total_channels": total_channels,
                "total_streams": total_streams,
            }
        })
    # Récupérer tous les noms de chaînes distincts depuis StreamInfo
    distinct_channels = StreamInfo.objects.values_list('channel', flat=True).distinct()

    # Rendre le template HTML pour les requêtes normales
    return render(request, "recherche.html", {
        "messages": messages_page,
        "total_pages": paginator.num_pages,
        "current_page": messages_page.number,
        "has_previous": messages_page.has_previous(),
        "has_next": messages_page.has_next(),
        "search_query": query_params['searchMessage'],
        "search_user": query_params['searchUser'],
        "sort_by": sort_by,
        "moderation_starttime": mod_startime,
        "moderation_uptime": mod_uptime,
        "all_statuses": unique_statuses,
        "items_from_db": distinct_channels,
        "selected_channels": query_params['selected_channels'],
        "total_messages": total_messages,
        "deleted_messages": deleted_messages,
        "total_users": total_users,
        "total_channels": total_channels,
        "total_streams": total_streams,
    })



"""
    Vue Django pour supprimer un fichier et toutes les données associées de la base de données.
    Cette vue accepte uniquement les requêtes POST contenant le nom du fichier à supprimer.
    Elle supprime les enregistrements liés au fichier dans les tables TwitchMessage, StreamInfo, et ViewerCount,
    puis supprime le fichier lui-même.
"""
def delete_filename(request):
    if request.method == "POST":
        filename = request.POST.get("filename", "").strip()
        print(f"Received filename for deletion: {filename}")

        if not filename:
            return JsonResponse({"status": "error", "message": "No filename provided"}, status=400)


        try:
            uploaded_file = UploadedFile.objects.get(filename=filename)
        except UploadedFile.DoesNotExist:
            return JsonResponse({"status": "error", "message": "File not found"}, status=404)


        twitch_messages_deleted, _ = TwitchMessage.objects.filter(uploaded_file=uploaded_file).delete()
        stream_info_deleted, _ = StreamInfo.objects.filter(uploaded_file=uploaded_file).delete()
        viewer_count_deleted, _ = ViewerCount.objects.filter(uploaded_file=uploaded_file).delete()

        print(f"Deleted {twitch_messages_deleted} TwitchMessage records.")
        print(f"Deleted {stream_info_deleted} StreamInfo records.")
        print(f"Deleted {viewer_count_deleted} ViewerCount records.")

        # Suppression de l'instance de UploadedFile elle-même
        uploaded_file.delete()
        print(f"Deleted UploadedFile: {filename}")


        # Renvoyer une réponse JSON indiquant le succès de la suppression
        return JsonResponse({
            "status": "success",
            "message": f"Deleted {twitch_messages_deleted + stream_info_deleted + viewer_count_deleted} records, including {filename}"
        })

    # Si la méthode de requête n'est pas POST, renvoyer une réponse d'erreur
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

"""
    Vue Django pour exporter des messages filtrés au format JSON.
    Cette vue récupère les messages Twitch associés à un fichier spécifique, applique des filtres et des tris,
    puis prépare les données pour être téléchargées sous forme de fichier JSON.
"""
def export_filtered_json(request):
    # filename = request.GET.get('file')
    # search_message = request.GET.get('searchMessage', '')
    # search_user = request.GET.get('searchUser', '')
    # sort_by = request.GET.get('sort', 'timestamp')

    query_params = get_common_request_params(request)

    try:
        filters = query_params['filters'] if query_params['filters'] else {}
    except json.JSONDecodeError:
        filters = {}

    if not query_params['file']:
        return JsonResponse({"error": "Filename is required"}, status=400)

    messages = TwitchMessage.objects.filter(uploaded_file__filename=query_params['file'])


    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')


    if query_params['searchMessage']:
        messages = messages.filter(message__icontains=query_params['searchMessage'])

    if query_params['searchUser']:
        messages = messages.filter(user__icontains=query_params['searchUser'])


    sort_by = query_params['sort']
    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp'

    messages = messages.order_by(sort_by)

    # Fetch des ViewerCount et StreamInfos
    viewer_counts = ViewerCount.objects.filter(uploaded_file__filename=query_params['file']).order_by('timestamp')
    stream_infos = StreamInfo.objects.filter(uploaded_file__filename=query_params['file']).order_by('-timestamp')

    # préparation des données JSON
    data = {
        "allMessages": [
            {
                "user": msg.user,
                "message": msg.message,
                "messageId": msg.message_id,
                "timestamp": msg.timestamp,
                "uptime": msg.uptime,
                "status": msg.status,
                "isModerated": msg.is_moderated,
                "sanction": msg.sanction,
                "duration": msg.duration,
                "moderation_uptime": msg.moderation_uptime,
                "moderation_starttime": msg.moderation_starttime,
            }
            for msg in messages
        ],
        "timeouts": [],
        "bans": [],
        "streaminfos": [
            {
                "channel": stream.channel,
                "title": stream.title,
                "category": stream.category,
                "language": stream.language,
                "isMature": stream.is_mature,
                "uptime": stream.uptime,
                "startTime": stream.start_time,
                "timestamp": stream.timestamp,
            }
            for stream in stream_infos
        ],
        "viewercount": [
            {
                "viewerCount": vc.viewer_count,
                "uptime": vc.uptime,
                "timestamp": vc.timestamp,
            }
            for vc in viewer_counts
        ],
    }


    json_file_name = "_".join(str(query_params['file']).split('_')[:-1])
    response = HttpResponse(
        json.dumps(data, indent=4, ensure_ascii=False),
        content_type="application/json"
    )
    response['Content-Disposition'] = f'attachment; filename="{json_file_name}_filtered.json"'
    return response


"""
    Vue Django pour exporter des messages filtrés au format CSV.
    Cette vue récupère les messages Twitch associés à un fichier spécifique, applique des filtres et des tris,
    puis prépare les données pour être téléchargées sous forme de fichier CSV.
"""

def export_filtered_csv(request):

    query_params = get_common_request_params(request)
    try:
        filters = query_params['filters'] if query_params['filters'] else {}
    except json.JSONDecodeError:
        filters = {}

    if not query_params['file']:
        return JsonResponse({"error": "Filename is required"}, status=400)

    messages = TwitchMessage.objects.filter(uploaded_file__filename=query_params['file'])


    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')


    if query_params['searchMessage']:
        messages = messages.filter(message__icontains=query_params['searchMessage'])

    if query_params['searchUser']:
        messages = messages.filter(user__icontains=query_params['searchUser'])


    sort_by = query_params['sort']
    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp'

    messages = messages.order_by(sort_by)

    csv_file_name = "_".join(str(query_params['file']).split('_')[:-1])
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{csv_file_name}_filtered.csv"'

    writer = csv.writer(response)
    writer.writerow(["User", "Message", "Message ID", "Timestamp", "Uptime", "Status", "Is Moderated", "Sanction", "Duration", "Moderation Uptime", "Moderation Starttime"])

    for msg in messages:
        writer.writerow([
            msg.user,
            msg.message,
            msg.message_id,
            msg.timestamp,
            msg.uptime,
            msg.status,
            msg.is_moderated,
            msg.sanction,
            msg.duration,
            msg.moderation_uptime,
            msg.moderation_starttime,
        ])

    return response



"""
    Vue Django pour exporter des messages filtrés au format XML.
    Cette vue récupère les messages Twitch associés à un fichier spécifique, applique des filtres et des tris,
    puis prépare les données pour être téléchargées sous forme de fichier XML.
"""
def export_filtered_xml(request):
    query_params = get_common_request_params(request)

    try:
        filters = query_params['filters'] if query_params['filters'] else {}
    except json.JSONDecodeError:
        filters = {}

    if not query_params['file']:
        return JsonResponse({"error": "Filename is required"}, status=400)

    messages = TwitchMessage.objects.filter(uploaded_file__filename=query_params['file'])

    if filters.get('modere') in ['true', 'false']:
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime') in ['true', 'false']:
        messages = messages.filter(sanction="Deleted") if filters['supprime'] == 'true' else messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')

    # Appliquer les filtres de recherche
    if query_params['searchMessage']:
        messages = messages.filter(message__icontains=query_params['searchMessage'])
    if query_params['searchUser']:
        messages = messages.filter(user__icontains=query_params['searchUser'])

    # Valider et appliquer le tri
    sort_by = query_params['sort']
    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp' if not sort_by.startswith('-') else '-timestamp'

    messages = messages.order_by(sort_by)

    viewer_counts = ViewerCount.objects.filter(uploaded_file__filename=query_params['file']).order_by('timestamp')
    stream_infos = StreamInfo.objects.filter(uploaded_file__filename=query_params['file']).order_by('-timestamp')

    root = ET.Element("data")

    all_messages = ET.SubElement(root, "allMessages")
    for msg in messages:
        message_elem = ET.SubElement(all_messages, "message")
        ET.SubElement(message_elem, "user").text = str(msg.user or "")
        ET.SubElement(message_elem, "message").text = str(msg.message or "")
        ET.SubElement(message_elem, "messageId").text = str(msg.message_id or "")
        ET.SubElement(message_elem, "timestamp").text = str(msg.timestamp or "")
        ET.SubElement(message_elem, "uptime").text = str(msg.uptime or "")
        ET.SubElement(message_elem, "status").text = str(msg.status or "")
        ET.SubElement(message_elem, "isModerated").text = str(msg.is_moderated or "")
        ET.SubElement(message_elem, "sanction").text = str(msg.sanction or "")
        ET.SubElement(message_elem, "duration").text = str(msg.duration or "")
        ET.SubElement(message_elem, "moderation_uptime").text = str(msg.moderation_uptime or "")
        ET.SubElement(message_elem, "moderation_starttime").text = str(msg.moderation_starttime or "")


    stream_infos_elem = ET.SubElement(root, "streaminfos")
    for stream in stream_infos:
        stream_elem = ET.SubElement(stream_infos_elem, "streaminfo")
        ET.SubElement(stream_elem, "channel").text = str(stream.channel or "")
        ET.SubElement(stream_elem, "title").text = str(stream.title or "")
        ET.SubElement(stream_elem, "category").text = str(stream.category or "")
        ET.SubElement(stream_elem, "language").text = str(stream.language or "")
        ET.SubElement(stream_elem, "isMature").text = str(stream.is_mature or "")
        ET.SubElement(stream_elem, "uptime").text = str(stream.uptime or "")
        ET.SubElement(stream_elem, "startTime").text = str(stream.start_time or "")
        ET.SubElement(stream_elem, "timestamp").text = str(stream.timestamp or "")


    viewer_counts_elem = ET.SubElement(root, "viewercount")
    for vc in viewer_counts:
        viewer_elem = ET.SubElement(viewer_counts_elem, "viewer")
        ET.SubElement(viewer_elem, "viewerCount").text = str(vc.viewer_count or "")
        ET.SubElement(viewer_elem, "uptime").text = str(vc.uptime or "")
        ET.SubElement(viewer_elem, "timestamp").text = str(vc.timestamp or "")

    # Créer un arbre XML et écrire dans la réponse
    xml_file_name = "_".join(str(query_params['file']).split('_')[:-1])
    tree = ET.ElementTree(root)
    response = HttpResponse(content_type="application/xml")
    response['Content-Disposition'] = f'attachment; filename="{xml_file_name}_filtered.xml"'
    tree.write(response, encoding='utf-8', xml_declaration=True)

    return response

"""
    Vue Django pour exporter tous les messages filtrés au format JSON.
    Cette vue permet de récupérer tous les messages Twitch ( elle s'applique pour l'export des messages depuis la vue globale), d'appliquer des filtres et des tris,
    puis de préparer les données pour être téléchargées sous forme de fichier JSON.
    
"""
def export_global_filtered_json(request):
    search_message = request.GET.get('searchMessage', '')
    search_user = request.GET.get('searchUser', '')
    sort_by = request.GET.get('sort', 'timestamp')
    channels = request.GET.getlist('channels')


    print("Channels received from request:", channels)

    filters = request.GET.get('filters', '{}')
    try:
        filters = json.loads(filters) if filters else {}
    except json.JSONDecodeError:
        filters = {}

    messages = TwitchMessage.objects.all()

    if channels:
        messages = messages.filter(uploaded_file__streaminfo__channel__in=channels)

    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')

    if search_message:
        messages = messages.filter(message__icontains=search_message)

    if search_user:
        messages = messages.filter(user__icontains=search_user)

    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp'

    messages = messages.order_by(sort_by)

    unique_message_ids = set()
    unique_messages = []

    for msg in messages:
        if msg.message_id not in unique_message_ids:
            unique_message_ids.add(msg.message_id)
            unique_messages.append(msg)

    data = {
        "allMessages": [
            {
                "user": msg.user,
                "message": msg.message,
                "messageId": msg.message_id,
                "timestamp": msg.timestamp,
                "uptime": msg.uptime,
                "status": msg.status,
                "isModerated": msg.is_moderated,
                "sanction": msg.sanction,
                "duration": msg.duration,
                "moderation_uptime": msg.moderation_uptime,
                "moderation_starttime": msg.moderation_starttime,
                "channel": StreamInfo.objects.filter(uploaded_file=msg.uploaded_file).first().channel if msg.uploaded_file else 'Unknown',
            }
            for msg in unique_messages
        ]
    }

    response = HttpResponse(
        json.dumps(data, indent=4, ensure_ascii=False),
        content_type="application/json"
    )
    response['Content-Disposition'] = 'attachment; filename="all_messages_filtered_by_channel.json"'
    return response


"""
    Vue Django pour exporter tous les messages filtrés au format XML.
    Cette vue permet de récupérer tous les messages Twitch, d'appliquer des filtres et des tris,
    puis de préparer les données pour être téléchargées sous forme de fichier XML.
"""

def export_global_filtered_xml(request):
    search_message = request.GET.get('searchMessage', '')
    search_user = request.GET.get('searchUser', '')
    sort_by = request.GET.get('sort', 'timestamp')
    channels = request.GET.getlist('channels')
    # Récupérer et parser les filtres JSON depuis la requête
    filters = request.GET.get('filters', '{}')
    try:
        filters = json.loads(filters) if filters else {}
    except json.JSONDecodeError:
        filters = {}

    messages = TwitchMessage.objects.all()


    if channels:
        messages = messages.filter(uploaded_file__streaminfo__channel__in=channels)

    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')


    if search_message:
        messages = messages.filter(message__icontains=search_message)

    if search_user:
        messages = messages.filter(user__icontains=search_user)

    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp'

    # Trier les messages selon le champ spécifié et garantir des messages distincts
    messages = messages.order_by(sort_by).distinct()
    # Récupérer les enregistrements ViewerCount et StreamInfo associés aux messages
    viewer_counts = ViewerCount.objects.filter(uploaded_file__in=messages.values_list('uploaded_file', flat=True)).order_by('timestamp')
    stream_infos = StreamInfo.objects.filter(uploaded_file__in=messages.values_list('uploaded_file', flat=True)).order_by('-timestamp')

    root = ET.Element("data")

    # Section des messages
    all_messages = ET.SubElement(root, "allMessages")
    processed_message_ids = set()

    for msg in messages:
        if msg.message_id in processed_message_ids:
            continue

        processed_message_ids.add(msg.message_id)
        message_elem = ET.SubElement(all_messages, "message")
        ET.SubElement(message_elem, "user").text = str(msg.user or "")
        ET.SubElement(message_elem, "message").text = str(msg.message or "")
        ET.SubElement(message_elem, "messageId").text = str(msg.message_id or "")
        ET.SubElement(message_elem, "timestamp").text = str(msg.timestamp or "")
        ET.SubElement(message_elem, "uptime").text = str(msg.uptime or "")
        ET.SubElement(message_elem, "status").text = str(msg.status or "")
        ET.SubElement(message_elem, "isModerated").text = str(msg.is_moderated or "")
        ET.SubElement(message_elem, "sanction").text = str(msg.sanction or "")
        ET.SubElement(message_elem, "duration").text = str(msg.duration or "")
        ET.SubElement(message_elem, "moderation_uptime").text = str(msg.moderation_uptime or "")
        ET.SubElement(message_elem, "moderation_starttime").text = str(msg.moderation_starttime or "")

    # Section des informations de stream
    stream_infos_elem = ET.SubElement(root, "streaminfos")
    for stream in stream_infos:
        stream_elem = ET.SubElement(stream_infos_elem, "streaminfo")
        ET.SubElement(stream_elem, "channel").text = str(stream.channel or "")
        ET.SubElement(stream_elem, "title").text = str(stream.title or "")
        ET.SubElement(stream_elem, "category").text = str(stream.category or "")
        ET.SubElement(stream_elem, "language").text = str(stream.language or "")
        ET.SubElement(stream_elem, "isMature").text = str(stream.is_mature or "")
        ET.SubElement(stream_elem, "uptime").text = str(stream.uptime or "")
        ET.SubElement(stream_elem, "startTime").text = str(stream.start_time or "")
        ET.SubElement(stream_elem, "timestamp").text = str(stream.timestamp or "")

    # Section des comptages de spectateurs
    viewer_counts_elem = ET.SubElement(root, "viewercount")
    for vc in viewer_counts:
        viewer_elem = ET.SubElement(viewer_counts_elem, "viewer")
        ET.SubElement(viewer_elem, "viewerCount").text = str(vc.viewer_count or "")
        ET.SubElement(viewer_elem, "uptime").text = str(vc.uptime or "")
        ET.SubElement(viewer_elem, "timestamp").text = str(vc.timestamp or "")

    # Créer un arbre XML et écrire dans la réponse
    xml_file_name = "filtered_messages"
    tree = ET.ElementTree(root)
    response = HttpResponse(content_type="application/xml")
    response['Content-Disposition'] = f'attachment; filename="{xml_file_name}.xml"'
    tree.write(response, encoding='utf-8', xml_declaration=True)

    return response



"""
    Vue Django pour exporter tous les messages filtrés au format CSV.
    Cette vue permet de récupérer tous les messages Twitch, d'appliquer des filtres et des tris,
    puis de préparer les données pour être téléchargées sous forme de fichier CSV.
"""

def export_global_filtered_csv(request):
    # Récupérer les paramètres de recherche et de tri depuis la requête GET
    search_message = request.GET.get('searchMessage', '')
    search_user = request.GET.get('searchUser', '')
    sort_by = request.GET.get('sort', 'timestamp')
    channels = request.GET.getlist('channels')

    print("Channels received from request:", channels)


    filters = request.GET.get('filters', '{}')
    try:
        filters = json.loads(filters) if filters else {}
    except json.JSONDecodeError:
        filters = {}

    messages = TwitchMessage.objects.all()


    if channels:
        messages = messages.filter(uploaded_file__streaminfo__channel__in=channels)

    if filters.get('modere'):
        messages = messages.filter(is_moderated=(filters['modere'] == 'true'))

    if filters.get('supprime'):
        if filters['supprime'] == 'true':
            messages = messages.filter(sanction="Deleted")
        elif filters['supprime'] == 'false':
            messages = messages.exclude(sanction="Deleted")

    if filters.get('status') and filters['status'].lower() != "all":
        selected_status = filters['status'].strip("[]'")
        messages = messages.filter(status__icontains=f'"{selected_status}"')

    if search_message:
        messages = messages.filter(message__icontains=search_message)

    if search_user:
        messages = messages.filter(user__icontains=search_user)

    valid_sort_fields = ['id', 'message', 'user', 'timestamp', 'uptime', 'is_moderated', 'sanction', 'duration', 'status']
    sort_field = sort_by.lstrip('-')

    if sort_field not in valid_sort_fields:
        sort_by = 'timestamp'

    messages = messages.order_by(sort_by)

    # Suivre les identifiants de message uniques pour éviter les doublons
    unique_message_ids = set()
    unique_messages = []
    for msg in messages:
        if msg.message_id not in unique_message_ids:
            unique_message_ids.add(msg.message_id)
            unique_messages.append(msg)

    # Préparer le fichier CSV
    csv_file_name = "filtered_messages"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{csv_file_name}.csv"'
    # Créer un objet writer pour écrire dans le fichier CSV
    writer = csv.writer(response)
    writer.writerow([
        "User", "Message", "Message ID", "Timestamp", "Uptime", "Status",
        "Is Moderated", "Sanction", "Duration", "Moderation Uptime",
        "Moderation Starttime", "Channel"
    ])

    # Écrire les données des messages dans le fichier CSV
    for msg in unique_messages:
        channel = StreamInfo.objects.filter(uploaded_file=msg.uploaded_file).first().channel if msg.uploaded_file else 'Unknown'
        writer.writerow([
            msg.user,
            msg.message,
            msg.message_id,
            msg.timestamp,
            msg.uptime,
            msg.status,
            msg.is_moderated,
            msg.sanction,
            msg.duration,
            msg.moderation_uptime,
            msg.moderation_starttime,
            channel
        ])

    return response