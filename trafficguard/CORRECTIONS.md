# Corrections apportées au moteur (version corrigée)

La logique de jugement a été fiabilisée. Corrections principales :

- **[C1] Mesure d'arrêt invariante à l'échelle** : le déplacement du centre est
  rapporté à la taille du véhicule (diagonale de la boîte), donc indépendant de
  la distance à la caméra et de la résolution.
- **[C2] Zone de contrôle cohérente** : région proportionnelle à la taille du
  panneau, au lieu d'une simple ligne sur le pixel du panneau.
- **[C3] Arrêt compté dans la zone** : l'immobilité n'est validée qu'à proximité
  du Stop.
- **[C4] Verdict robuste** : rendu au point de plus proche approche du panneau,
  indépendamment du sens de circulation.
- **[C5] Lissage de la trajectoire** : réduit les faux arrêts / faux mouvements.
- **[C6] Réglages regroupés et proportionnels** : calibrage simple et robuste.

Le reste de l'application (app.py, interface, déploiement) est inchangé.
