import json
import os
from django.conf import settings
from django.db import models
from django.utils.timezone import make_aware
from datetime import datetime



"""
Ce fichier models.py est l'un des composant essentiel de Django. Il permet de définir les structures 
de données qui seront utilisées pour stocker des informations dans une base de données relationnelle. 
Ce modèle est déstiné a stocker les informations relatives à des streams sur twitch à des fins d'analyse ultérieure.

"""

class UploadedFile(models.Model):
    """Modèle pour stocker des noms de fichiers uniques.
    Ce modèle sert de référence centrale pour tous les fichiers téléchargés dans l'application."""
    # Champs 'id' : Clé primaire auto-incrémentée, utilisée comme clé substitut par défaut dans Django.

    id = models.AutoField(primary_key=True)
    filename = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.filename

"""
 Clé étrangère vers le modèle UploadedFile, établissant une relation avec un fichier téléchargé.
 Champ 'channel' : Nom de la chaîne Twitch.
 Champ 'title' : Titre du stream.
 Champ 'category' : Catégorie du stream.
 Champ 'language' : Langue du stream.
 Champ 'is_mature' : Indicateur si le contenu est réservé à un public adulte.
 Champ 'uptime' : Temps écoulé depuis le début du stream, stocké sous forme de chaîne.
 Champ 'start_time' : Heure de début du stream, stockée sous forme de chaîne.
 Champ 'timestamp' : Horodatage du stream, stocké sous forme de chaîne.
"""
class StreamInfo(models.Model):
    uploaded_file = models.ForeignKey(UploadedFile, on_delete=models.CASCADE)
    channel = models.CharField(max_length=255)
    title = models.TextField()
    category = models.CharField(max_length=255)
    language = models.CharField(max_length=10)
    is_mature = models.BooleanField(default=False)
    uptime = models.CharField(max_length=255)
    start_time = models.CharField(max_length=255)
    timestamp = models.CharField(max_length=255)



    class Meta:
        # Contrainte d'unicité sur plusieurs champs pour éviter les doublons.
        unique_together = ("uploaded_file", "channel", "title", "category", "start_time", "timestamp")

    def __str__(self):
        return f"{self.channel} - {self.title} ({self.uploaded_file.filename})"

"""

Modèle de la base de données stockant les messages et les informations associèes:
elle contient :

message            : Contenu du message de chat.
user               : Nom de l'utilisateur ayant envoyé le message.
message_id         : Identifiant unique du message. (défini dans le fichier JSON)
timestamp          : Horodatage du message, stocké sous forme de chaîne.
uptime             : Temps écoulé depuis le début du stream lorsque le message a été envoyé.
status             : Statut de l'utilisateur ayant posté le message, stocké sous forme de JSON.
is_moderated       : Indicateur si le message a été modéré.
sanction           : Type de sanction appliquée au message.
duration           : Durée de la sanction.
moderation_uptime  : Temps écoulé depuis le début du stream lorsque la modération a eu lieu.
moderation_starttime : Heure de début de la modération.

"""

class TwitchMessage(models.Model):
    # Clé étrangère vers le modèle UploadedFile, établissant une relation avec un fichier téléchargé.
    uploaded_file = models.ForeignKey(UploadedFile, on_delete=models.CASCADE)
    message = models.TextField()
    user = models.CharField(max_length=255)
    message_id = models.CharField(max_length=255, unique=True)
    timestamp = models.CharField(max_length=255)
    uptime = models.CharField(max_length=255, blank=True, null=True)
    status = models.JSONField(default=list)
    is_moderated = models.BooleanField(default=False)
    sanction = models.CharField(max_length=10, choices=[
        ("Deleted", "Deleted"),
        ("Timeout", "Timeout"),
        ("Ban", "Ban"),
        (None, "None"),
    ], blank=True, null=True)
    duration = models.CharField(max_length=20, blank=True, null=True)
    moderation_uptime = models.CharField(max_length=255, blank=True, null=True)
    moderation_starttime = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.user}: {self.message[:50]}..."



"""
La structure de la base de données Viewercount, définit le nombre de viewers au fil du stream. les champs de cette table sont les sivants :
UploadedFile : Clé etrangère permettant la relation avec un fichier uploadé.
viewercount  : Nombre de spectateurs
uptime       : Temps écoulé depuis le début du stream lorsque le comptage a été enregistré.
timestamp    : Horodatage du comptage, stocké sous forme de chaîne.
"""


class ViewerCount(models.Model) :
    # Clé étrangère vers le modèle UploadedFile, établissant une relation avec un fichier téléchargé.
    uploaded_file = models.ForeignKey(UploadedFile, on_delete=models.CASCADE)
    viewer_count = models.IntegerField()
    uptime = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.CharField(max_length=255)


    class Meta:
        # Contrainte d'unicité sur plusieurs champs pour éviter les doublons.
        unique_together = ("uploaded_file", "timestamp", "viewer_count")

    def __str__(self):
        # Méthode pour retourner une représentation sous forme de chaîne de l'objet.
        return f"{self.viewer_count} viewers at {self.timestamp} ({self.uploaded_file.filename})"




