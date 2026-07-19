# ============================================================
# Dockerfile - Recette de construction de l'environnement
# Projet : TrafficGuard
# ------------------------------------------------------------
# Un Dockerfile decrit, etape par etape, comment installer
# l'application sur un serveur vierge. Hugging Face Spaces
# l'utilise pour deployer le projet en ligne.
# ============================================================

# On part d'une image Python 3.11 legere ("slim").
FROM python:3.11-slim

# Tout le travail se fait dans le dossier /app.
WORKDIR /app

# --- Dependances systeme requises par OpenCV ---
# OpenCV a besoin de quelques bibliotheques graphiques de bas
# niveau qui ne sont pas incluses dans l'image Python slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Dependances Python ---
# On copie d'abord SEULEMENT requirements.txt puis on installe.
# Ainsi, tant que ce fichier ne change pas, Docker reutilise
# cette etape en cache (construction plus rapide).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Code de l'application ---
COPY . .

# Dossier des fichiers uploades temporairement.
RUN mkdir -p /app/uploads && chmod 777 /app/uploads

# Hugging Face Spaces communique sur le port 7860.
EXPOSE 7860

# Commande lancee au demarrage du conteneur.
CMD ["python", "app.py"]
