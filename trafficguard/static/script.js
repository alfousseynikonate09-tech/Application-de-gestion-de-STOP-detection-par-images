// ============================================================
// script.js - Logique de l'interface TrafficGuard
// Projet : Detection d'Infractions aux Panneaux Stop
// ------------------------------------------------------------
// Ce fichier gere TOUT ce qui se passe dans le navigateur :
//   - le choix entre le mode Video et le mode Image,
//   - l'envoi du fichier au serveur (upload),
//   - le lancement de l'analyse,
//   - la mise a jour de l'affichage en temps reel (polling).
//
// "Polling" = demander regulierement au serveur "ou en es-tu ?".
// Ici, toutes les 250 millisecondes pendant une analyse video.
// ============================================================

// ---- Variables globales ----
let modeActuel = "video";       // "video" ou "image"
let intervallePolling = null;   // identifiant du polling en cours
let timeoutAlerte = null;       // pour masquer la banniere d'alerte
let infractionsPrecedent = 0;   // pour detecter une NOUVELLE infraction
let respecteesPrecedent = 0;    // idem pour les "respectees"


// Petit raccourci : recuperer un element par son id.
function $(id) {
  return document.getElementById(id);
}


// ============================================================
// INITIALISATION (au chargement de la page)
// ============================================================
document.addEventListener("DOMContentLoaded", function () {

  // Boutons principaux.
  $("btn-lancer").addEventListener("click", lancerAnalyse);
  $("btn-pause").addEventListener("click", basculerPause);
  $("btn-stop").addEventListener("click", arreterAnalyse);

  // Bascule Video / Image.
  $("btn-mode-video").addEventListener("click", () => changerMode("video"));
  $("btn-mode-image").addEventListener("click", () => changerMode("image"));

  // Selection d'un fichier.
  $("input-fichier").addEventListener("change", function () {
    const fichier = this.files[0];
    if (fichier) {
      $("depot-nom").textContent = fichier.name;
      $("depot").classList.add("charge");
      cacherErreur();
    }
  });
});


// ============================================================
// CHANGER DE MODE (Video <-> Image)
// ============================================================
function changerMode(mode) {
  modeActuel = mode;

  // Mettre a jour l'apparence des boutons de bascule.
  $("btn-mode-video").classList.toggle("actif", mode === "video");
  $("btn-mode-image").classList.toggle("actif", mode === "image");

  // Adapter le champ de fichier et les textes selon le mode.
  if (mode === "video") {
    $("input-fichier").setAttribute("accept", "video/*");
    $("depot-texte").textContent = "Cliquez pour choisir une vidéo";
    $("depot-formats").textContent = "MP4, AVI, MOV, MKV";
  } else {
    $("input-fichier").setAttribute("accept", "image/*");
    $("depot-texte").textContent = "Cliquez pour choisir une image";
    $("depot-formats").textContent = "JPG, PNG, BMP, WEBP";
  }

  // Reinitialiser la selection de fichier.
  $("input-fichier").value = "";
  $("depot-nom").textContent = "";
  $("depot").classList.remove("charge");
  cacherErreur();
}


// ============================================================
// LANCER L'ANALYSE
// ------------------------------------------------------------
// Etape 1 : envoyer le fichier au serveur (upload).
// Etape 2 : selon le type, lancer une analyse video ou image.
// ============================================================
function lancerAnalyse() {
  const input = $("input-fichier");

  // Verifier qu'un fichier est selectionne.
  if (!input.files || input.files.length === 0) {
    afficherErreur("Veuillez d'abord choisir un fichier.");
    return;
  }

  cacherErreur();
  reinitialiserInterface();

  const bouton = $("btn-lancer");
  bouton.disabled = true;
  $("btn-lancer-texte").textContent = "Envoi en cours...";

  // Afficher la barre de progression de l'upload.
  $("upload-barre").classList.add("visible");
  const jauge = $("upload-jauge");
  jauge.style.width = "0%";

  // Preparer le fichier a envoyer.
  const formData = new FormData();
  formData.append("fichier", input.files[0]);

  // On utilise XMLHttpRequest (et non fetch) car il permet de
  // suivre la progression de l'upload, ce que fetch ne fait pas.
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");

  // Mise a jour de la barre pendant l'upload.
  xhr.upload.onprogress = function (e) {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      jauge.style.width = pct + "%";
      $("btn-lancer-texte").textContent = "Envoi " + pct + "%";
    }
  };

  // Quand l'upload est termine.
  xhr.onload = function () {
    $("upload-barre").classList.remove("visible");

    if (xhr.status !== 200) {
      reinitialiserBouton();
      afficherErreur("Erreur lors de l'envoi du fichier.");
      return;
    }

    const reponse = JSON.parse(xhr.responseText);
    if (reponse.statut !== "ok") {
      reinitialiserBouton();
      afficherErreur(reponse.message || "Erreur inconnue.");
      return;
    }

    // Le fichier est sur le serveur. On lance la bonne analyse.
    if (reponse.type === "image") {
      lancerAnalyseImage(reponse.chemin);
    } else {
      lancerAnalyseVideo(reponse.chemin);
    }
  };

  // En cas d'erreur reseau.
  xhr.onerror = function () {
    $("upload-barre").classList.remove("visible");
    reinitialiserBouton();
    afficherErreur("Impossible de joindre le serveur.");
  };

  xhr.send(formData);
}


// ============================================================
// ANALYSE VIDEO
// ============================================================
function lancerAnalyseVideo(chemin) {
  $("btn-lancer-texte").textContent = "Démarrage...";

  fetch("/api/demarrer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: chemin }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.statut === "erreur") {
        reinitialiserBouton();
        afficherErreur(data.message || "Impossible de démarrer l'analyse.");
        return;
      }
      
      // Le bouton reste désactivé pendant toute la durée de l'analyse vidéo
      $("btn-lancer").disabled = true;
      $("btn-lancer-texte").textContent = "Analyse en cours...";

      // Activer le bouton de pause
      $("btn-pause").disabled = false;
      majInterfacePause(false);

      // Reinitialiser les compteurs locaux.
      infractionsPrecedent = 0;
      respecteesPrecedent = 0;

      // Mettre l'interface en mode "analyse en cours".
      majBadgeStatut("actif", "Analyse en cours");
      $("mode-actif").textContent = "VIDÉO";
      $("barre-video").classList.add("visible");
      $("historique-vide").style.display = "none";

      // Demarrer le polling : on interroge le serveur 4 fois/seconde.
      if (intervallePolling) clearInterval(intervallePolling);
      intervallePolling = setInterval(actualiser, 250);
    })
    .catch(() => {
      reinitialiserBouton();
      afficherErreur("Impossible de démarrer l'analyse vidéo.");
    });
}


// ============================================================
// ANALYSE IMAGE
// ------------------------------------------------------------
// Une image se traite en une seule fois : pas de polling.
// ============================================================
function lancerAnalyseImage(chemin) {
  $("btn-lancer-texte").textContent = "Analyse...";

  fetch("/api/analyser-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: chemin }),
  })
    .then((r) => r.json())
    .then((data) => {
      reinitialiserBouton();

      if (data.statut !== "ok") {
        afficherErreur(data.message || "Erreur lors de l'analyse.");
        return;
      }

      // Afficher l'image annotee.
      const media = $("media-rendu");
      media.src = "data:image/jpeg;base64," + data.frame;
      media.style.display = "block";
      $("ecran-vide").style.display = "none";

      // Mettre a jour les informations.
      $("mode-actif").textContent = "IMAGE";
      majBadgeStatut("fini", "Analyse terminée");

      // Mettre a jour la carte du panneau Stop.
      majCarteStop(data.stops > 0, data.stops);

      // En mode image, on n'affiche PAS d'infraction (impossible
      // a juger sur une photo). On montre seulement ce qui a ete
      // detecte, dans l'historique.
      const historique = $("historique");
      $("historique-vide").style.display = "none";
      historique.innerHTML = `
        <div class="evenement">
          <div class="evenement-point respecte"></div>
          <div class="evenement-texte respecte">
            ${data.stops} panneau(x) Stop, ${data.vehicules} véhicule(s)
          </div>
          <div class="evenement-heure">image</div>
        </div>
        <div class="historique-vide" style="margin-top:10px">
          Le jugement d'infraction nécessite une vidéo.
        </div>`;
    })
    .catch(() => {
      reinitialiserBouton();
      afficherErreur("Impossible d'analyser l'image.");
    });
}


// ============================================================
// ARRETER L'ANALYSE
// ============================================================
function arreterAnalyse() {
  fetch("/api/arreter", { method: "POST" }).catch(() => {});

  if (intervallePolling) {
    clearInterval(intervallePolling);
    intervallePolling = null;
  }

  majBadgeStatut("arrete", "Arrêté");
  $("barre-video").classList.remove("visible");
  reinitialiserBouton();
}


// ============================================================
// ACTUALISER L'INTERFACE (appelee en boucle pendant une video)
// ============================================================
function actualiser() {
  fetch("/api/etat")
    .then((r) => r.json())
    .then((etat) => {

      // ---- Afficher l'image analysee ----
      if (etat.frame) {
        const media = $("media-rendu");
        media.src = "data:image/jpeg;base64," + etat.frame;
        media.style.display = "block";
        $("ecran-vide").style.display = "none";
      }

      // ---- Gerer une erreur renvoyee par le serveur ----
      if (etat.erreur) {
        afficherErreur(etat.erreur);
        arreterPolling();
        majBadgeStatut("arrete", "Erreur");
        return;
      }

      // ---- Barre de progression de la video ----
      $("barre-video-jauge").style.width = (etat.progression || 0) + "%";

      // ---- Carte du panneau Stop ----
      majCarteStop(etat.stop_detecte, null);

      // ---- Vehicules suivis ----
      $("stat-vehicules").textContent = etat.vehicules_actifs || 0;

      // ---- Compteur d'infractions ----
      // Si le chiffre a augmente, c'est une NOUVELLE infraction :
      // on anime le chiffre et on affiche la banniere d'alerte.
      if (etat.infractions !== infractionsPrecedent) {
        if (etat.infractions > infractionsPrecedent) {
          animerChiffre("stat-infractions");
          afficherAlerte();
        }
        infractionsPrecedent = etat.infractions;
      }
      $("stat-infractions").textContent = etat.infractions || 0;

      // ---- Compteur de respectees ----
      if (etat.respectees !== respecteesPrecedent) {
        if (etat.respectees > respecteesPrecedent) {
          animerChiffre("stat-respectees");
        }
        respecteesPrecedent = etat.respectees;
      }
      $("stat-respectees").textContent = etat.respectees || 0;

      // ---- Historique des evenements ----
      majHistorique(etat.historique);

      // ---- Synchroniser l'état de pause ----
      if (etat.en_cours) {
        majInterfacePause(etat.pause);
      }

      // ---- Fin de l'analyse ----
      if (!etat.en_cours) {
        arreterPolling();
        majBadgeStatut("fini", "Analyse terminée");
        $("barre-video-jauge").style.width = "100%";
        reinitialiserBouton();
      }
    })
    .catch((err) => console.error("Erreur de polling :", err));
}


// ============================================================
// FONCTIONS UTILITAIRES
// ============================================================

/* Met a jour la carte du panneau Stop. */
function majCarteStop(detecte, nombre) {
  const carte = $("carte-stop");
  const sous = $("carte-stop-sous");

  if (detecte) {
    carte.classList.add("detecte");
    if (nombre !== null && nombre !== undefined) {
      sous.textContent = nombre + " panneau(x) détecté(s)";
    } else {
      sous.textContent = "Panneau STOP détecté";
    }
  } else {
    carte.classList.remove("detecte");
    sous.textContent = "Aucun panneau détecté";
  }
}

/* Reconstruit la liste de l'historique. */
function majHistorique(historique) {
  if (!historique || historique.length === 0) return;

  const conteneur = $("historique");
  conteneur.innerHTML = historique
    .map((e) => {
      const libelle =
        e.type === "infraction" ? "Infraction" : "Arrêt respecté";
      return `
        <div class="evenement">
          <div class="evenement-point ${e.type}"></div>
          <div class="evenement-texte ${e.type}">
            ${libelle} — ${e.texte}
          </div>
          <div class="evenement-heure">${e.heure}</div>
        </div>`;
    })
    .join("");
}

/* Met a jour le badge de statut en haut a droite. */
function majBadgeStatut(type, texte) {
  const badge = $("badge-statut");
  const point = $("point-statut");

  badge.classList.remove("actif", "fini");
  point.classList.remove("actif", "fini");

  if (type === "actif") {
    badge.classList.add("actif");
    point.classList.add("actif");
  } else if (type === "fini") {
    badge.classList.add("fini");
    point.classList.add("fini");
  }
  $("texte-statut").textContent = texte;
}

/* Anime brievement un chiffre (effet "rebond"). */
function animerChiffre(id) {
  const el = $(id);
  el.classList.remove("rebond");
  void el.offsetWidth; // force le navigateur a "redemarrer" l'animation
  el.classList.add("rebond");
}

/* Affiche la banniere d'alerte pendant 3 secondes. */
function afficherAlerte() {
  const alerte = $("alerte");
  alerte.classList.add("visible");
  if (timeoutAlerte) clearTimeout(timeoutAlerte);
  timeoutAlerte = setTimeout(() => {
    alerte.classList.remove("visible");
  }, 3000);
}

/* Stoppe le polling. */
function arreterPolling() {
  if (intervallePolling) {
    clearInterval(intervallePolling);
    intervallePolling = null;
  }
}

/* Remet le bouton "Lancer" dans son etat normal. */
function reinitialiserBouton() {
  const bouton = $("btn-lancer");
  bouton.disabled = false;
  $("btn-lancer-texte").textContent = "Lancer l'analyse";

  // Désactiver et réinitialiser le bouton de pause
  const btnPause = $("btn-pause");
  btnPause.disabled = true;
  majInterfacePause(false);
}

/* Bascule l'état de pause de la vidéo sur le serveur. */
function basculerPause() {
  fetch("/api/pause", { method: "POST" })
    .then((r) => r.json())
    .then((data) => {
      if (data.statut === "ok") {
        majInterfacePause(data.pause);
      } else {
        afficherErreur(data.message || "Erreur de mise en pause.");
      }
    })
    .catch(() => {
      afficherErreur("Impossible de communiquer avec le serveur.");
    });
}

/* Met à jour graphiquement le bouton Pause et le statut selon l'état actuel. */
function majInterfacePause(estEnPause) {
  const btnPause = $("btn-pause");
  const textePause = $("btn-pause-texte");
  
  if (estEnPause) {
    btnPause.classList.add("pause-active");
    textePause.textContent = "Reprendre";
    // Remplacer l'icône pause par une icône de lecture (Play)
    const svg = btnPause.querySelector("svg");
    if (svg) {
      svg.setAttribute("width", "12");
      svg.setAttribute("height", "12");
      svg.innerHTML = `<polygon points="6 4 20 12 6 20 6 4" />`;
    }
    // Mettre à jour le badge de statut
    majBadgeStatut("actif", "En pause");
  } else {
    btnPause.classList.remove("pause-active");
    textePause.textContent = "Pause";
    // Remplacer l'icône de lecture par une icône pause
    const svg = btnPause.querySelector("svg");
    if (svg) {
      svg.setAttribute("width", "12");
      svg.setAttribute("height", "12");
      svg.innerHTML = `<rect x="4" y="4" width="4" height="16" rx="1" /><rect x="16" y="4" width="4" height="16" rx="1" />`;
    }
    // Si le badge est en cours, s'assurer que le texte indique bien "Analyse en cours"
    const badge = $("badge-statut");
    if (badge && badge.classList.contains("actif")) {
      $("texte-statut").textContent = "Analyse en cours";
    }
  }
}

/* Affiche un message d'erreur. */
function afficherErreur(message) {
  const div = $("erreur");
  div.textContent = message;
  div.classList.add("visible");
}

/* Cache le message d'erreur. */
function cacherErreur() {
  $("erreur").classList.remove("visible");
}

/* Réinitialise les éléments de l'interface graphique (compteurs, images, etc.) avant une nouvelle analyse. */
function reinitialiserInterface() {
  // Masquer l'image précédente et réafficher l'écran vide
  $("media-rendu").style.display = "none";
  $("media-rendu").src = "";
  $("ecran-vide").style.display = "flex";
  
  // Réinitialiser les compteurs
  $("stat-infractions").textContent = "0";
  $("stat-respectees").textContent = "0";
  $("stat-vehicules").textContent = "0";
  
  infractionsPrecedent = 0;
  respecteesPrecedent = 0;

  // Réinitialiser la carte Stop
  majCarteStop(false, null);
  
  // Réinitialiser l'historique
  const historique = $("historique");
  historique.innerHTML = `<div class="historique-vide" id="historique-vide">Aucun événement pour l'instant</div>`;
  
  // Cacher l'alerte
  $("alerte").classList.remove("visible");
  if (timeoutAlerte) clearTimeout(timeoutAlerte);
  
  // Cacher la barre vidéo
  $("barre-video").classList.remove("visible");
  $("barre-video-jauge").style.width = "0%";
}
