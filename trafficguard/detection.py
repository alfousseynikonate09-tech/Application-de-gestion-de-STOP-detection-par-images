# ============================================================
# detection.py - Moteur de detection des infractions au STOP
# Projet : TrafficGuard - Detection d'Infractions aux Panneaux Stop
# ------------------------------------------------------------
# VERSION CORRIGEE + ZONE DE CONTROLE PARAMETRABLE.
# Corrections / ameliorations (detaillees dans le rapport) :
#   [C1] Mesure d'arret invariante a l'echelle (ratio, et non pixels bruts)
#   [C2] Zone de controle autour du panneau (region, pas une simple ligne)
#   [C3] L'arret n'est comptabilise que DANS la zone controlee
#   [C5] Lissage de la trajectoire pour absorber le bruit de detection
#   [C6] Reglages regroupes et exprimes en proportions
#   [C7] ZONE DE CONTROLE PARAMETRABLE : l'operateur delimite la portion de
#        chaussee reellement regie par le panneau (ZONE_ROUTE). Seuls les
#        vehicules circulant dans cette zone sont juges ; ceux des routes
#        voisines (ou stationnes ailleurs) sont ignores.
#   [C8] Verdict rendu au point de plus proche approche du panneau
#        (independant du sens de circulation), tant que le vehicule est
#        dans la zone controlee.
# ============================================================
import cv2
import numpy as np
import threading
import time
import base64
import os
from collections import deque
from ultralytics import YOLO

# ============================================================
# REGLAGES [C6]
# ============================================================
SEUIL_CONFIANCE = 0.35
RATIO_ARRET = 0.008            # [C1] deplacement / diagonale de la boite
DUREE_ARRET_MIN = 0.5          # secondes d'immobilite pour valider un arret
FENETRE_LISSAGE = 3            # [C5]
MIN_VUES_AVANT_JUGEMENT = 5
MEMOIRE_VEHICULE = 60
MEMOIRE_STOP = 90

# [C7] ZONE DE CONTROLE PARAMETRABLE
# ------------------------------------------------------------
# Liste de points (x, y) en FRACTIONS de la largeur/hauteur de l'image,
# decrivant le polygone de la route regie par le panneau Stop.
# Mettre ZONE_ROUTE = None pour revenir a la zone automatique deduite
# de la position du panneau (rectangle proportionnel a sa taille).
# La calibration ci-dessous correspond a la video de demonstration
# fournie (la route du haut, le long de laquelle se trouve le panneau).
ZONE_ROUTE = None
# Parametres de la zone automatique (utilises si ZONE_ROUTE est None).
ZONE_FACTEUR_LARGEUR = 6.0
ZONE_FACTEUR_HAUTEUR = 7.0
ZONE_MIN_FRACTION = 0.12
ZONE_MAX_FRACTION = 0.85

CLASSES_VEHICULES = {2, 3, 5, 7}
CLASSE_STOP = 11
NOMS_CLASSES = {2: "Voiture", 3: "Moto", 5: "Bus", 7: "Camion"}

COULEUR_INFRACTION = (60, 60, 230)
COULEUR_RESPECTE = (90, 200, 90)
COULEUR_NEUTRE = (220, 170, 70)
COULEUR_STOP = (40, 40, 210)
COULEUR_ZONE = (70, 180, 240)


def _point_dans_polygone(x, y, poly):
    """Test d'appartenance d'un point a un polygone (ray casting)."""
    n = len(poly)
    dedans = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            dedans = not dedans
        j = i
    return dedans


class Vehicule:
    def __init__(self, identifiant_global):
        self.id = identifiant_global
        self.positions = deque(maxlen=90)
        self.tailles = deque(maxlen=90)
        self.instants = deque(maxlen=90)
        self.a_marque_arret = False
        self.deja_juge = False
        self.verdict = None
        self.frames_immobiles = 0
        self.frames_absent = 0
        self.a_visite_zone = False
        self.vues_en_zone = 0
        self.dist_min = None          # [C8] plus proche approche du panneau
        self.frames_apres_min = 0
        self.disp_zone = deque(maxlen=90)  # deplacements relatifs dans la zone
        self.etait_dans_zone = False

    def ajouter_position(self, cx, cy, diag, instant, fps, dans_zone):
        self.positions.append((cx, cy))
        self.tailles.append(max(1.0, diag))
        self.instants.append(instant)
        self.frames_absent = 0
        if dans_zone:
            self.a_visite_zone = True
            self.vues_en_zone += 1
        if len(self.positions) < 2:
            return
        x_prec, y_prec = self.positions[-2]
        deplacement = float(np.hypot(cx - x_prec, cy - y_prec))
        deplacement_relatif = deplacement / self.tailles[-1]   # [C1]
        if dans_zone:                                           # [C3]
            self.disp_zone.append(deplacement_relatif)
            requis = max(3, int(DUREE_ARRET_MIN * fps))
            recents = list(self.disp_zone)[-requis:]
            if len(recents) >= requis:
                # mediane robuste au bruit de detection [C5]
                med = float(np.median(recents))
                if med < RATIO_ARRET:
                    self.a_marque_arret = True
                self.frames_immobiles = sum(1 for d in recents if d < RATIO_ARRET)
        self.etait_dans_zone = dans_zone


class DetecteurVideo:
    def __init__(self):
        self.etat = {
            "infractions": 0, "respectees": 0, "stop_detecte": False,
            "vehicules_actifs": 0, "historique": [], "en_cours": False,
            "pause": False, "frame": None, "erreur": None,
            "progression": 0, "mode": None,
        }
        self.verrou = threading.Lock()
        self.verrou_modele = threading.Lock()
        self.paused = False
        self.prochain_id_global = 1
        self.map_id_bytetrack_global = {}
        self.stop_memoire_zones = []
        self.stop_memoire_frames = 0
        print("Chargement du modele YOLO...")
        chemin_modele = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yolov8n.pt")
        self.modele = YOLO(chemin_modele)
        print("Modele YOLO pret.")

    def demarrer(self, source, mode="video"):
        with self.verrou:
            if self.etat.get("en_cours"):
                return False
            self.paused = False
            self.etat.update({
                "infractions": 0, "respectees": 0, "stop_detecte": False,
                "vehicules_actifs": 0, "historique": [], "en_cours": True,
                "pause": False, "frame": None, "erreur": None,
                "progression": 0, "mode": mode,
            })
            self.prochain_id_global = 1
            self.map_id_bytetrack_global = {}
            self.stop_memoire_zones = []
            self.stop_memoire_frames = 0
        threading.Thread(target=self._analyser_video, args=(source,), daemon=True).start()
        return True

    def analyser_image(self, source):
        try:
            image = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            image = None
        if image is None:
            return {"statut": "erreur", "message": "Impossible de lire l'image."}
        h, w = image.shape[:2]
        if w > 1280:
            e = 1280 / w
            image = cv2.resize(image, (1280, int(h * e)))
        with self.verrou_modele:
            resultats = self.modele(image, conf=SEUIL_CONFIANCE, verbose=False)[0]
        nb_stops = nb_vehicules = 0
        for b in resultats.boxes:
            c = int(b.cls[0]); conf = float(b.conf[0])
            x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
            if c == CLASSE_STOP:
                nb_stops += 1
                cv2.rectangle(image, (x1, y1), (x2, y2), COULEUR_STOP, 3)
                self._etiquette(image, "PANNEAU STOP", x1, y1, COULEUR_STOP)
            elif c in CLASSES_VEHICULES:
                nb_vehicules += 1
                nom = NOMS_CLASSES.get(c, "Vehicule")
                cv2.rectangle(image, (x1, y1), (x2, y2), COULEUR_NEUTRE, 2)
                self._etiquette(image, f"{nom} {conf:.0%}", x1, y1, COULEUR_NEUTRE)
        return {"statut": "ok", "stops": nb_stops, "vehicules": nb_vehicules,
                "frame": self._encoder_image(image)}

    def arreter(self):
        with self.verrou:
            self.etat["en_cours"] = False
            self.paused = False

    def basculer_pause(self):
        with self.verrou:
            if not self.etat["en_cours"]:
                return False
            self.paused = not self.paused
            self.etat["pause"] = self.paused
            return True

    def get_etat(self):
        with self.verrou:
            c = dict(self.etat); c["historique"] = list(self.etat["historique"])
            return c

    def _polygone_route(self, w, h):
        if ZONE_ROUTE is None:
            return None
        return [(int(x * w), int(y * h)) for (x, y) in ZONE_ROUTE]

    def _analyser_video(self, source):
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            with self.verrou:
                self.etat["en_cours"] = False
                self.etat["erreur"] = "Impossible d'ouvrir la video."
            return
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 120:
                fps = 25.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            try:
                orientation = cap.get(cv2.CAP_PROP_ORIENTATION_META)
            except AttributeError:
                orientation = 0
            vehicules = {}
            numero = 0
            while True:
                paused = False
                with self.verrou:
                    if not self.etat["en_cours"]:
                        break
                    if self.paused:
                        paused = True
                if paused:
                    time.sleep(0.1); continue
                ret, frame = cap.read()
                if not ret:
                    break
                numero += 1
                instant = numero / fps
                if orientation == 90: frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif orientation == 180: frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif orientation == 270: frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                h, w = frame.shape[:2]
                if w > 960:
                    e = 960 / w; frame = cv2.resize(frame, (960, int(h * e))); h, w = frame.shape[:2]

                with self.verrou_modele:
                    res = self.modele.track(frame, conf=SEUIL_CONFIANCE, persist=True,
                                            tracker="bytetrack.yaml", verbose=False)[0]

                # 1) panneaux Stop
                zones_stop = []
                for b in res.boxes:
                    if int(b.cls[0]) == CLASSE_STOP:
                        x1, y1, x2, y2 = b.xyxy[0].tolist()
                        zones_stop.append((x1, y1, x2, y2))
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), COULEUR_STOP, 3)
                        self._etiquette(frame, "STOP", int(x1), int(y1), COULEUR_STOP)
                if zones_stop:
                    self.stop_memoire_zones = list(zones_stop); self.stop_memoire_frames = MEMOIRE_STOP
                elif self.stop_memoire_frames > 0:
                    zones_stop = list(self.stop_memoire_zones); self.stop_memoire_frames -= 1
                stop_present = len(zones_stop) > 0
                sign_c = None
                if zones_stop:
                    p = max(zones_stop, key=lambda z: (z[2]-z[0])*(z[3]-z[1]))
                    sign_c = ((p[0]+p[2])/2.0, (p[1]+p[3])/2.0)

                poly = self._polygone_route(w, h)            # [C7]
                zone_auto = None if poly else self._zone_auto(zones_stop, w, h)

                # 2) vehicules
                ids = set()
                for b in res.boxes:
                    c = int(b.cls[0])
                    if c not in CLASSES_VEHICULES or b.id is None:
                        continue
                    x1, y1, x2, y2 = b.xyxy[0].tolist()
                    if x2 <= 0 or x1 >= w or y2 <= 0 or y1 >= h:
                        continue
                    idb = int(b.id[0]); conf = float(b.conf[0]); ids.add(idb)
                    cx = (x1+x2)/2.0; cy = (y1+y2)/2.0; diag = float(np.hypot(x2-x1, y2-y1))
                    if idb not in vehicules:
                        self.map_id_bytetrack_global[idb] = self.prochain_id_global
                        vehicules[idb] = Vehicule(self.prochain_id_global); self.prochain_id_global += 1
                    v = vehicules[idb]
                    # Un vehicule est "controle" s'il est dans la zone ET qu'un Stop regit la scene
                    if poly is not None:
                        dz = stop_present and _point_dans_polygone(cx, cy, poly)
                    else:
                        dz = stop_present and self._dans_rect(cx, cy, zone_auto)
                    avant = v.etait_dans_zone
                    v.ajouter_position(cx, cy, diag, instant, fps, dz)
                    # [C8] Deux declencheurs de verdict :
                    #  (1) un vehicule qui CIRCULE est juge lorsqu'il s'eloigne
                    #      de son point de plus proche approche du panneau ;
                    #  (2) un vehicule a l'arret est juge a la SORTIE de la zone.
                    # Un vehicule stationne hors trajectoire n'est jamais accuse a tort.
                    if dz and sign_c is not None and not v.deja_juge:
                        d = float(np.hypot(cx - sign_c[0], cy - sign_c[1]))
                        if v.dist_min is None or d < v.dist_min:
                            v.dist_min = d; v.frames_apres_min = 0
                        else:
                            v.frames_apres_min += 1
                        net = float(np.hypot(cx - v.positions[0][0], cy - v.positions[0][1]))
                        if (net > 1.5 * diag and v.vues_en_zone >= MIN_VUES_AVANT_JUGEMENT
                                and v.frames_apres_min >= 1):
                            self._rendre_verdict(v)
                    if (not v.deja_juge and v.a_visite_zone and avant and (not dz)
                            and v.vues_en_zone >= MIN_VUES_AVANT_JUGEMENT):
                        self._rendre_verdict(v)
                    self._dessiner_vehicule(frame, v, c, conf, x1, y1, x2, y2, dz)

                # 3) vehicules disparus
                for idv in list(vehicules.keys()):
                    if idv not in ids:
                        v = vehicules[idv]; v.frames_absent += 1
                        if (not v.deja_juge and v.a_visite_zone and v.vues_en_zone >= MIN_VUES_AVANT_JUGEMENT):
                            self._rendre_verdict(v)
                        if v.frames_absent > MEMOIRE_VEHICULE:
                            del vehicules[idv]
                            self.map_id_bytetrack_global.pop(idv, None)

                # 4) dessiner la zone controlee
                if poly is not None and stop_present:
                    pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(frame, [pts], True, COULEUR_ZONE, 2)
                    self._etiquette(frame, "ZONE CONTROLEE", poly[0][0], max(26, poly[0][1]), COULEUR_ZONE)
                elif zone_auto is not None:
                    cv2.rectangle(frame, (int(zone_auto["x1"]), int(zone_auto["y1"])),
                                  (int(zone_auto["x2"]), int(zone_auto["y2"])), COULEUR_ZONE, 2)

                with self.verrou:
                    self.etat["frame"] = self._encoder_image(frame)
                    self.etat["stop_detecte"] = stop_present
                    self.etat["vehicules_actifs"] = len(ids)
                    if total > 0:
                        self.etat["progression"] = int(100 * numero / total)
                time.sleep(0.04)
        except Exception as e:
            with self.verrou:
                self.etat["erreur"] = f"Erreur durant l'analyse : {str(e)}"
        finally:
            cap.release()
            with self.verrou:
                self.etat["en_cours"] = False; self.etat["progression"] = 100

    def _rendre_verdict(self, v):
        v.deja_juge = True
        if v.a_marque_arret:
            v.verdict = "respecte"
            with self.verrou:
                self.etat["respectees"] += 1
                self._ajouter_historique("respecte", f"Vehicule #{v.id}")
        else:
            v.verdict = "infraction"
            with self.verrou:
                self.etat["infractions"] += 1
                self._ajouter_historique("infraction", f"Vehicule #{v.id}")

    def _zone_auto(self, zones_stop, w, h):
        if not zones_stop:
            return None
        p = max(zones_stop, key=lambda z: (z[2]-z[0])*(z[3]-z[1]))
        scx = (p[0]+p[2])/2.0; scy = (p[1]+p[3])/2.0
        pw = max(1.0, p[2]-p[0]); ph = max(1.0, p[3]-p[1])
        dl = min(max(pw*ZONE_FACTEUR_LARGEUR/2, w*ZONE_MIN_FRACTION/2), w*ZONE_MAX_FRACTION/2)
        dh = min(max(ph*ZONE_FACTEUR_HAUTEUR/2, h*ZONE_MIN_FRACTION/2), h*ZONE_MAX_FRACTION/2)
        return {"x1": max(0, scx-dl), "x2": min(w, scx+dl), "y1": max(0, scy-dh), "y2": min(h, scy+dh)}

    def _dans_rect(self, cx, cy, z):
        return z is not None and z["x1"] <= cx <= z["x2"] and z["y1"] <= cy <= z["y2"]

    def _dessiner_vehicule(self, frame, v, classe, conf, x1, y1, x2, y2, dz):
        p1 = (int(x1), int(y1)); p2 = (int(x2), int(y2))
        nom = NOMS_CLASSES.get(classe, "Vehicule")
        if v.verdict == "infraction":
            cv2.rectangle(frame, p1, p2, COULEUR_INFRACTION, 3)
            self._etiquette(frame, f"INFRACTION #{v.id}", int(x1), int(y1), COULEUR_INFRACTION)
        elif v.verdict == "respecte":
            cv2.rectangle(frame, p1, p2, COULEUR_RESPECTE, 3)
            self._etiquette(frame, f"RESPECTE #{v.id}", int(x1), int(y1), COULEUR_RESPECTE)
        else:
            cv2.rectangle(frame, p1, p2, COULEUR_NEUTRE, 2)
            if dz and v.a_marque_arret:
                t = f"{nom} #{v.id} - arret detecte"
            elif dz and v.frames_immobiles > 0:
                t = f"{nom} #{v.id} - ralentit"
            elif dz:
                t = f"{nom} #{v.id} - sous controle"
            else:
                t = f"{nom} #{v.id}"
            self._etiquette(frame, t, int(x1), int(y1), COULEUR_NEUTRE)

    def _etiquette(self, image, texte, x, y, couleur):
        x = max(0, x); y = max(18, y)
        f = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), base = cv2.getTextSize(texte, f, 0.5, 1)
        cv2.rectangle(image, (x, y-th-base-6), (x+tw+8, y), couleur, -1)
        cv2.putText(image, texte, (x+4, y-base-2), f, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def _encoder_image(self, image):
        _, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf).decode("utf-8")

    def _ajouter_historique(self, t, txt):
        self.etat["historique"].insert(0, {"type": t, "texte": txt, "heure": time.strftime("%H:%M:%S")})
        if len(self.etat["historique"]) > 8:
            self.etat["historique"].pop()
