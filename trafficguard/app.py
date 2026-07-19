# ============================================================
# app.py - Serveur web Flask
# Projet : TrafficGuard - Detection d'Infractions aux Panneaux Stop
# ------------------------------------------------------------
# Ce fichier est le "pont" entre :
#   - le navigateur (interface HTML/CSS/JS), et
#   - le moteur de detection (detection.py).
#
# Flask recoit les requetes du navigateur (uploader une video,
# demarrer l'analyse, demander l'etat...) et appelle les bonnes
# methodes du detecteur.
# ============================================================

import os
from flask import Flask, render_template, jsonify, request
from detection import DetecteurVideo

# Creation de l'application Flask.
app = Flask(__name__)
# Taille maximale d'un fichier uploade : 150 Mo.
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

# Dossier ou sont stockes temporairement les fichiers uploades.
# Utilise un chemin relatif au projet pour eviter les problemes de droits sous Windows et Colab.
DOSSIER_UPLOAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(DOSSIER_UPLOAD, exist_ok=True)

# Extensions de fichiers acceptees.
EXTENSIONS_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
EXTENSIONS_IMAGE = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# UNE seule instance du detecteur, partagee par toute l'application.
# Le modele YOLO se charge ici, une seule fois, au demarrage.
detecteur = DetecteurVideo()


# ============================================================
# ROUTES (les "adresses" de l'application)
# ============================================================

@app.route("/")
def accueil():
    """Page principale : renvoie l'interface web."""
    return render_template("index.html")


@app.route("/api/etat")
def get_etat():
    """
    Renvoie l'etat courant de l'analyse (compteurs, image, etc.).
    Le navigateur appelle cette route en boucle pour s'actualiser.
    """
    return jsonify(detecteur.get_etat())


@app.route("/api/upload", methods=["POST"])
def upload_fichier():
    """
    Recoit un fichier (video OU image) envoye par le navigateur,
    le sauvegarde, et indique de quel type il s'agit.
    """
    # Bloquer l'upload si une analyse est déjà en cours (evite le verrouillage de fichier sous Windows)
    if detecteur.get_etat().get("en_cours"):
        return jsonify({"statut": "erreur",
                        "message": "Une analyse est déjà en cours. Veuillez l'arrêter avant de charger un nouveau fichier."}), 400

    if "fichier" not in request.files:
        return jsonify({"statut": "erreur",
                        "message": "Aucun fichier recu."}), 400

    fichier = request.files["fichier"]
    if fichier.filename == "":
        return jsonify({"statut": "erreur",
                        "message": "Aucun fichier selectionne."}), 400

    # Recuperer l'extension (.mp4, .jpg, ...) en minuscules.
    extension = os.path.splitext(fichier.filename)[1].lower()

    if extension in EXTENSIONS_VIDEO:
        type_fichier = "video"
        chemin = os.path.join(DOSSIER_UPLOAD, "media_analyse" + extension)
    elif extension in EXTENSIONS_IMAGE:
        type_fichier = "image"
        chemin = os.path.join(DOSSIER_UPLOAD, "media_analyse" + extension)
    else:
        return jsonify({
            "statut": "erreur",
            "message": "Format non supporte. Utilisez MP4/AVI/MOV "
                       "pour les videos ou JPG/PNG pour les images.",
        }), 400

    fichier.save(chemin)
    return jsonify({"statut": "ok", "chemin": chemin,
                    "type": type_fichier})


@app.route("/api/demarrer", methods=["POST"])
def demarrer_analyse():
    """Lance l'analyse d'une VIDEO uploadee."""
    donnees = request.get_json(silent=True) or {}
    source = (donnees.get("source") or "").strip()

    if not source:
        return jsonify({"statut": "erreur",
                        "message": "Aucune source fournie."}), 400

    if not detecteur.demarrer(source, mode="video"):
        return jsonify({"statut": "erreur",
                        "message": "Une analyse est déjà en cours. Veuillez l'arrêter avant d'en lancer une nouvelle."}), 400

    return jsonify({"statut": "demarre"})


@app.route("/api/analyser-image", methods=["POST"])
def analyser_image():
    """
    Analyse une IMAGE fixe et renvoie directement le resultat.
    (Pas de polling : une image se traite en une fois.)
    """
    donnees = request.get_json(silent=True) or {}
    source = (donnees.get("source") or "").strip()

    if not source:
        return jsonify({"statut": "erreur",
                        "message": "Aucune source fournie."}), 400

    resultat = detecteur.analyser_image(source)
    return jsonify(resultat)


@app.route("/api/arreter", methods=["POST"])
def arreter_analyse():
    """Arrete l'analyse video en cours."""
    detecteur.arreter()
    return jsonify({"statut": "arrete"})


@app.route("/api/pause", methods=["POST"])
def basculer_pause():
    """Bascule l'état de pause de l'analyse vidéo."""
    if detecteur.basculer_pause():
        return jsonify({"statut": "ok", "pause": detecteur.paused})
    return jsonify({"statut": "erreur", "message": "Aucune analyse en cours."}), 400


# ============================================================
# EN-TETES CORS
# ------------------------------------------------------------
# Necessaires pour que l'application fonctionne correctement
# lorsqu'elle est exposee via ngrok ou Hugging Face Spaces.
# ============================================================
@app.after_request
def ajouter_headers(reponse):
    reponse.headers["Access-Control-Allow-Origin"] = "*"
    reponse.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    reponse.headers["Access-Control-Allow-Headers"] = "Content-Type"
    reponse.headers["ngrok-skip-browser-warning"] = "1"
    return reponse


# ============================================================
# LANCEMENT DU SERVEUR
# ============================================================
if __name__ == "__main__":
    # Le port 7860 est celui attendu par Hugging Face Spaces.
    port = int(os.environ.get("PORT", 7860))
    print(f"Serveur TrafficGuard demarre sur le port {port}")
    # threaded=True : permet de traiter les requetes du navigateur
    # pendant que l'analyse video tourne dans son propre thread.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
