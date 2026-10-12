# Annotation et mesure des fissures

## Démarrage

Dans VS Code, **Ctrl+Maj+B** sur le dossier `identification fissure` ; ou
double-clic sur `../Lancer.cmd` ; ou `../run_annotation_app.ps1`. Le navigateur
s'ouvre tout seul (voir le README du dossier pour le premier lancement sur un
nouveau poste). Après une mise à jour du code serveur, arrêter et relancer ce lanceur, puis
actualiser la page. Les changements d’interface et de mesure ne nécessitent
pas de recalculer les masques déjà en cache.

## Tracer et corriger

1. Sélectionner une tuile. Le premier clic dans une autre tuile la sélectionne
   seulement ; il ne dessine rien.
2. **C — Tracer** : poser deux points, puis continuer à cliquer pour prolonger
   le même tracé. Le calcul suit l’image et chaque paire de nœuds est routée.
3. **Échap** termine et conserve le tracé sans lui imposer une catégorie. Le
   mode repasse en Sélection : le clic suivant ne démarre pas une nouvelle
   fissure. Pendant un calcul, la fin est appliquée dès son enregistrement.
   Avec un seul point non enregistré, Échap annule ce point.
4. **V — Sélection** : cliquer sur un tracé pour le sélectionner. Sélectionner
   un tracé non classé ne le remet plus automatiquement en cours de dessin.
5. **+ Nœud** : après avoir sélectionné une fissure, cliquer n’importe où sur
   sa ligne pour insérer un nœud exactement à cet endroit. Le mode reste actif
   afin d’en ajouter plusieurs et **Échap** permet de le quitter. Un clic hors
   de la ligne ne modifie pas la fissure. La catégorie est conservée.
   **Maj-clic** sur le tracé sélectionné permet aussi l’insertion directe.
   Déplacer ensuite une poignée pour ajuster le tracé.
6. **Z — Retirer point** retire le dernier point pendant un nouveau tracé,
   sans déplacer la vue. Avec deux points, le premier est conservé. Clic droit
   sur une poignée retire ce nœud si au moins deux nœuds restent.
7. Attribuer une catégorie avec les boutons ou les touches physiques 1 / 2 / 3
   (AZERTY : & / é / "). Mixte reste accessible par bouton.
8. Valider la tuile une fois relue. La catégorisation et la validation de tuile
   sont deux opérations distinctes.

**Ctrl+Z** annule la dernière action ; **Suppr** rejette le tracé sélectionné.
Le glisser déplace l’image, Espace masque temporairement les lignes locales.
La grille s’active par **Grille** ; la tuile sélectionnée a un contour bleu.

## Un seul panneau : Vue et mesures

Le bouton **Vue et mesures** ouvre le panneau commun. Il remplace l’ancien
menu local Vue et l’ancien tableau séparé Longueurs.

Les choix **Périmètre** (tuile sélectionnée ou mosaïque), **Mesurer** (tracés
 enregistrés ou axes automatiques calculés), et **Limiter aux tuiles validées**
sont visibles au-dessus des onglets. Les réglages de superposition servent
au bilan, à la superposition des axes mesurés et aux exports.

- **Couches** : mêmes choix pour la tuile et la mosaïque — score, masque,
  squelette, axes automatiques finaux, coût automatique, coût du tracé manuel.
  Opacité réglable. Les régions transparentes sont non calculées.
  Le calcul du périmètre est annulable après la tuile en cours et reprend
  depuis le cache. Les cases de couleur filtrent la superposition des axes du
  bilan ; elles ne suppriment pas de catégories des tableaux ou des figures.
- **Bilan** : longueur cumulée, longueurs par catégorie et quantité de
  superposition retirée.
  Les modifications locales actualisent ce bilan lorsqu’il est ouvert.
  **Actualiser** relit aussi les changements faits par d’autres annotateurs.
- **Figures** : carte des axes, longueurs par catégorie, longueur par tuile,
  orientation pondérée par longueur. Les figures reprennent exactement les
  filtres et la tolérance du bilan. Export PNG, SVG, PDF ou CSV des segments.

## Superpositions et sens du compteur

Par défaut, les portions longitudinalement superposées, parallèles à cinq
 degrés près et distantes de moins de **2 px**, comptent une seule fois. La
 règle conserve la géométrie du premier identifiant de tracé et retire les
 portions redondantes des suivants, sans modifier les annotations enregistrées.
 Une portion portant plusieurs catégories différentes devient **Conflit**.

La tolérance est réglable sous **Règle de superposition** ; 0 px conserve
 uniquement le dédoublonnage exact. Deux fissures physiques réellement
 parallèles à moins de la tolérance peuvent être regroupées : choisir une
 tolérance plus faible pour les distinguer.

### Limite mesurée du dédoublonnage

**Le dédoublonnage ne résiste pas à un redessin à main levée.** La règle est un
seuil dur sur la distance perpendiculaire : deux tracés qui suivent la même
fissure en oscillant autour l'un de l'autre ne sont fusionnés que là où ils
restent dans la tolérance ; partout ailleurs la longueur est comptée deux fois.

Mesuré en redessinant une fissure réelle de 3 590 px (182 nœuds) avec un
tremblement latéral :

| écart latéral du second tracé | longueur totale | erreur |
| --- | --- | --- |
| 0 px, copie exacte | 3 590 | 0 % |
| σ = 1 px | 4 213 | +17 % |
| σ = 1,5 px | 5 014 | **+40 %** |
| décalage uniforme de 2,1 px | 4 321 | +20 % |

Monter la tolérance ne sauve pas le cas : à 5 px, l'erreur reste de +30 % et on
commence à fusionner des fissures parallèles réellement distinctes.

**Conséquence pratique : ne pas retracer une fissure déjà tracée.** Corriger le
tracé existant en déplaçant ses poignées, ou le supprimer avant d'en refaire un.
Le total affiché est une somme de tracés, pas une mesure de la fissuration.

Il n'y a volontairement **pas de compteur de fissures**. Un nombre de fissures
suppose de décider ce qui relie deux tracés — jonction, croisement, simple
proximité — et aucune de ces règles n'est vérifiable à l'œil dans l'interface
en l'état. Un chiffre invérifiable est pire que pas de chiffre.

La longueur est euclidienne et exprimée en pixels de l’image originale.
Ce n’est ni une aire de masque ni un nombre de pixels de squelette. La part
 colmatée utilise seulement `colmaté / (ouvert + colmaté)` ; mixte, incertain,
 non classé et conflit restent en dehors de ce dénominateur.

Les axes automatiques ne reçoivent jamais de catégorie colmaté/non colmaté.
Les tuiles non calculées sont exclues et signalées, et ne valent pas zéro
 fissure. Les masques de diagnostic et leur export ZIP/NPZ conservent la
 résolution d’analyse et leurs coordonnées originales ; ils ne mesurent pas
 l’aire ou la largeur physique des fissures.

## Collaboration et conservation

Un seul serveur partage sa base SQLite entre les navigateurs. Les révisions
 empêchent l’écrasement silencieux d’une modification concurrente. Les tracés
 rejetés sont exclus des mesures ; l’historique est conservé. La détection ne
 remplace pas le travail existant. Les visualisations et exports ne créent
 pas d’annotations. Les scripts historiques de référence restent inchangés.

## Vérification

Depuis le dossier `identification fissure`, avec le Python du projet
(`..\.venv\…` sur le poste d'origine) :

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m unittest discover
& $py .\validation\validate_editing_ui.py
& $py .\validation\validate_analysis_ui.py
& $py .\validation\validate_zoom_ui.py
& $py .\evaluate_crack_detection.py
```

Les tests navigateur utilisent des copies SQLite, leur propre cache d'analyse
 et leurs propres profils Chrome ; ils ne modifient ni les annotations de
 travail ni le cache en service. Les rapports et captures sont dans
 `validation\sorties\`. L’évaluation inclut les tuiles
 validées vides pour mesurer les faux positifs. Réserver des régions hors
 apprentissage pour évaluer un nouveau modèle ; ne pas régler les seuils sur
 le seul résultat visuel d’une tuile.
