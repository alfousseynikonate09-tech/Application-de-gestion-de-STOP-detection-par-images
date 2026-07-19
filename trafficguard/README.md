# TrafficGuard — Détection d'Infractions aux Panneaux Stop

Projet de Fin d'Études — Licence Génie Informatique — 2025/2026

## Présentation

TrafficGuard est une application web qui analyse une vidéo de circulation,
détecte les panneaux Stop, suit les véhicules, et détermine si chaque
véhicule a marqué l'arrêt obligatoire.

Le système distingue :
- les véhicules en INFRACTION (n'ont pas marqué l'arrêt) ;
- les véhicules ayant RESPECTÉ l'arrêt.

## Contenu du dossier

    trafficguard/
    ├── app.py              Serveur web (Flask)
    ├── detection.py        Moteur d'analyse (YOLO + ByteTrack)
    ├── requirements.txt    Bibliothèques à installer
    ├── Dockerfile          Recette de déploiement en ligne
    ├── templates/
    │   └── index.html      Structure de la page web
    └── static/
        ├── style.css       Apparence de l'interface
        └── script.js       Logique côté navigateur

## Installation rapide (en local)

    pip install -r requirements.txt
    python app.py

Puis ouvrir http://localhost:7860 dans un navigateur.

## Installation sur Google Colab

Voir le document "Guide_TrafficGuard" fourni avec le projet : il détaille
chaque étape (activation du GPU, installation, mise en ligne via ngrok).

## Les deux modes

- Mode Vidéo : analyse complète, jugement des infractions inclus.
- Mode Image : détection des panneaux Stop et des véhicules uniquement.
  Le jugement d'infraction n'est PAS possible sur une image fixe, car une
  infraction se mesure dans le temps (absence d'arrêt). Cette limite est
  volontaire et assumée.

## Remarque importante sur les vidéos de test

Le système mesure si un véhicule s'immobilise à l'écran. Cela suppose une
caméra FIXE. Utiliser des vidéos de caméras de surveillance d'intersection,
et non des vidéos filmées depuis un véhicule en mouvement (dashcam).

## Technologies

Python, YOLOv8, ByteTrack, OpenCV, NumPy, Flask, HTML/CSS/JavaScript, Docker.
