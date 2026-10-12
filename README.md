# Identification des fissures

Tout ce qui sert au projet aujourd'hui. Les scripts abandonnés ou remplacés
sont dans `..\anciens scripts\`.

## Lancer l'application

Le dossier fonctionne **où qu'on le copie** : aucun chemin n'est écrit en dur.
Trois façons équivalentes :

- **VS Code** : *Fichier > Ouvrir le dossier…* sur `identification fissure`
  lui-même (pas sur un dossier parent), puis **Ctrl+Maj+B**. Les autres actions
  sont dans *Terminal > Exécuter la tâche…* : choisir une autre image, lancer
  les tests ;
- **double-clic** sur `Lancer.cmd` (ou `Choisir une image.cmd`) ;
- **terminal** : `.\run_annotation_app.ps1`, avec `-Choisir` pour changer
  d'image.

Ce qui se passe tout seul :

- **premier lancement sur un poste** : l'environnement Python est créé dans
  `.venv\`, à côté du lanceur, avec exactement les versions du poste d'origine
  (`constraints_annotation_app.txt`). Quelques minutes, environ 1 Go, une seule
  fois. Il faut seulement un Python 3.10 à 3.13, 64 bits, installé sur le poste ;
- **l'image** : la dernière ouverte sur ce poste. La première fois, une fenêtre
  demande de la choisir ;
- **le port** : 8000, ou le suivant s'il est pris ;
- **le navigateur** s'ouvre quand le serveur est prêt. `Ctrl+C` dans le
  terminal arrête le serveur.

Le mode d'emploi de l'interface est dans
[`annotation_app/README.md`](annotation_app/README.md) : raccourcis, flux de
travail.

## Donner l'application à un collègue

```powershell
.\preparer_copie.ps1 -Destination E:\
```

copie le code et les modèles de détection (5 Mo), sans ce qui est propre à ce
poste : environnement Python, base, cache, sauvegardes. Options :

- `-AvecAnnotations` joint une copie de la base : le collègue part du travail
  déjà fait. Ses annotations vivent ensuite dans sa copie, sans retour vers la
  vôtre ;
- `-Image "D:\MEB\mosaique.tif"` joint une mosaïque, dans
  `images\` — là où la fenêtre de choix s'ouvre en premier.

Chez le collègue : ouvrir le dossier dans VS Code, **Ctrl+Maj+B**. Copier le
dossier à la main marche aussi, mais emporte plusieurs Go de cache inutile
ailleurs (`annotation_app\data\`).

Sur un poste neuf, si l'installation échoue derrière un proxy, définir
`$env:HTTPS_PROXY` avant de relancer. Si VS Code demande de faire confiance au
dossier, accepter : les tâches de lancement en dépendent.

## Partager un serveur en réseau

`-Partager` ouvre le serveur aux autres postes (par défaut, il n'écoute que
le poste local). Le lanceur affiche alors les adresses utilisables, avec le
nom de leur réseau : donner celle du réseau du laboratoire, pas celle d'un VPN
ou d'un Wi-Fi. L'adresse est distribuée par DHCP et peut changer — relire la
bannière à chaque lancement.

**Sur un poste géré, le partage peut être bloqué sans recours de notre côté.**
Il arrive que le pare-feu Windows soit désactivé par la stratégie de groupe et
que les connexions entrantes soient filtrées par un autre logiciel de
sécurité, géré par l'informatique. Une règle `New-NetFirewallRule` n'a alors
aucun effet, et il faut de toute façon être administrateur. Le lanceur détecte
ce cas et nomme le logiciel en cause.

Pour savoir où ça bloque, depuis le poste du collègue, serveur lancé :

```powershell
Test-NetConnection ADRESSE -Port 8000
```

- `PingSucceeded : True` mais `TcpTestSucceeded : False` : le poste est
  joignable, le port est bloqué — demander à l'informatique d'ouvrir l'entrée
  TCP 8000 sur ce poste, depuis le réseau du labo seulement ;
- les deux à `False` : le réseau isole les postes — informatique aussi ;
- `TcpTestSucceeded : True` : tout est ouvert, `http://ADRESSE:8000` doit
  marcher, et `http://ADRESSE:8000/api/health` répondre `{"status":"ok",...}`.

À terme, héberger l'application sur un serveur du labo évite de dépendre de ce
poste et de son adresse.

Ne pas contourner le problème en posant la base SQLite sur un lecteur réseau
avec un serveur par poste : le verrouillage de SQLite n'est pas fiable sur un
partage Windows, la base peut se corrompre.

Si l'informatique installe un poste où le pare-feu Windows est actif, le
lanceur indique au contraire la commande `New-NetFirewallRule` à passer.

## Changer de mosaïque

Tâche VS Code *Fissures : choisir une autre image*, double-clic sur
`Choisir une image.cmd`, ou :

```powershell
.\run_annotation_app.ps1 -Choisir
.\run_annotation_app.ps1 -Image "D:\MEB\mosaique.tif"
```

L'image choisie devient celle des lancements suivants. Un second lancement
pendant que le premier tourne prend le port suivant : deux images peuvent être
ouvertes en parallèle.

L'identifiant qui sépare les annotations d'une mosaïque de celles d'une autre
est **déduit du fichier**, dans cet ordre :

1. le chemin est déjà enregistré : on reprend son identifiant et son travail ;
2. le fichier a été **déplacé ou renommé** : une seule image enregistrée a
   disparu de son ancien emplacement et a exactement les mêmes dimensions — on
   la reprend, et le serveur l'annonce dans le terminal ;
3. sinon, image nouvelle : identifiant tiré du nom, avec un suffixe (`-2`, `-3`…)
   s'il est déjà pris. Deux `RECALAGE.tif` de deux échantillons ne partagent
   donc jamais leurs tracés.

Deux recalages d'une même mosaïque n'ont jamais exactement les mêmes
dimensions : ils restent séparés, c'est voulu, leurs coordonnées diffèrent.

`-ImageId` force l'identifiant. Le serveur refuse qu'il soit déjà celui d'une
autre image (sinon les tracés de l'une réapparaîtraient sur l'autre, sans
message), ou qu'une même image en porte deux. Pour **repartir de zéro** sur une
image déjà annotée, utiliser `-Database` avec une base neuve.

Les réglages existent aussi en variables d'environnement, utiles pour les
scripts : `CRACK_IMAGE_PATH`, `CRACK_IMAGE_ID`, `CRACK_DATABASE_PATH`, ainsi que
`CRACK_BACKUP_DIR` et `CRACK_CACHE_DIR` (voir plus bas). Le lanceur ne laisse
pas les trois premières derrière lui : il repart d'une ardoise vide et
restaure l'état de la session en sortant, sans quoi un lancement sans argument
imposerait une image oubliée dans le terminal. **Sans argument, il ouvre donc
toujours la dernière image ouverte sur ce poste**, mémorisée dans
`annotation_app\data\derniere_image.txt`. Les deux dernières variables, elles,
sont respectées : on peut les définir une fois pour toutes dans les variables
d'environnement de Windows.

## Sauvegardes

Tout le travail d'annotation tient dans `annotation_app\data\annotations.sqlite3`.
Le serveur en fait une copie **à chaque démarrage, avant d'y écrire quoi que ce
soit**, puis **toutes les 4 heures** tant qu'il tourne. Les copies vont dans
`annotation_app\data\sauvegardes\`, sous la forme
`annotations-AAAAMMJJ-HHMMSS.sqlite3`. Une copie identique à la précédente
n'est pas conservée. Celles de plus de 14 jours sont retirées, mais les 10 plus
récentes restent toujours, même après un long arrêt.

Une copie sur le même disque ne protège pas d'une panne ou d'un vol de ce
disque. Mieux vaut désigner un lecteur réseau, une fois pour toutes :

```powershell
[Environment]::SetEnvironmentVariable("CRACK_BACKUP_DIR", "H:\Sauvegardes fissures", "User")
```

Pour restaurer : arrêter le serveur, remplacer `annotations.sqlite3` par la
copie choisie (et supprimer `annotations.sqlite3-wal` et `-shm` s'ils
existent), relancer.

## Cache d'analyse

`annotation_app\data\analysis_cache\` garde les cartes de score, masques et
propositions déjà calculés, un dossier par mosaïque et par version du modèle
et du code de détection. Un réentraînement ou une retouche de la détection
crée donc un nouveau dossier. Au démarrage, le serveur supprime l'ancien
dossier de **la même mosaïque**, ainsi que les dossiers vides. Il ne touche
jamais aux caches des autres mosaïques. Tout ce cache se recalcule si on
l'efface ; il en coûte seulement du temps.

Deux limites à connaître. La mosaïque doit être un TIFF **non compressé à une
seule bande** : c'est ce qui permet de la lire par `memmap` sans jamais la
charger entière. Et le réseau de repérage a été entraîné sur celle-ci ; sur un
échantillon différent, la détection automatique sera moins bonne, voire
mauvaise, jusqu'à un réentraînement.

## Ce que contient ce dossier

| | |
| --- | --- |
| `annotation_app/` | l'application web : interface, base SQLite, tuilage, détection |
| `annotation_app/modeles/` | les modèles de détection ; ils voyagent avec le code |
| `annotation_app/data/` | l'état de **ce poste** : base, cache, sauvegardes, dernière image. Ne se copie pas d'un poste à l'autre |
| `run_annotation_app.ps1` | lance le serveur et ouvre le navigateur ; installe l'environnement au premier lancement |
| `Lancer.cmd`, `Choisir une image.cmd` | la même chose en double-clic |
| `.vscode/tasks.json` | les mêmes actions dans VS Code (Ctrl+Maj+B) |
| `preparer_copie.ps1` | prépare une copie propre pour un collègue |
| `requirements_annotation_app.txt`, `constraints_annotation_app.txt` | les dépendances, et leurs versions exactes |
| `crack_length_analysis_multi.py` | le cœur historique : carte de coût, routage, lissage, mesure des longueurs. **Fichier de référence de l'utilisateur, à ne pas modifier.** L'application l'importe |
| `crop_roi.py` | lecture par `memmap` et découpe des mosaïques géantes. Importé par le tuilage |
| `train_crack_unet.py` | réentraîne le réseau de segmentation qui repère les fissures |
| `train_crack_detector.py` | réentraîne le modèle par pixel, gardé en repli |
| `evaluate_crack_detection.py` | le banc de mesure : précision, rappel, F1 contre les tracés humains |
| `tests/` | tests de l'application, de la détection et des mesures de longueur |
| `validation/` | outils de contrôle qui pilotent un vrai navigateur ; leurs sorties vont dans `validation/sorties/`, non versionnées |
| `TOPO_IDENTIFICATION.md` | document de passation : tout ce qui a été mesuré, ce qui marche, ce qu'il ne faut pas refaire |

## Mosaïque de référence

La mosaïque dont les tuiles validées servent de vérité terrain est désignée
**sur chaque poste, hors du dépôt** : le code ne contient aucun nom
d'échantillon. Écrire son chemin, une ligne, dans
`annotation_app\data\image_reference.txt` (ou définir `CRACK_REFERENCE_IMAGE`).
Elle sert alors :

- d'image par défaut au banc et aux entraînements, et aux tests qui lisent une
  vraie mosaïque. Sans elle, le banc prend la dernière image ouverte, ou
  `--image`, et ces tests sont sautés ;
- d'image ouverte par le lanceur, à défaut de dernière image.

Si un `.venv\` fonctionnel existe dans le dossier parent, le lanceur le reprend
tant qu'il n'y en a pas dans le projet.

## Commandes utiles

Depuis ce dossier, avec l'interpréteur du projet (ou `..\.venv\…` sur le poste
d'origine) :

```powershell
$py = ".\.venv\Scripts\python.exe"

# Mesurer la détection sur toutes les tuiles validées
& $py .\evaluate_crack_detection.py

# Essai rapide sur huit tuiles
& $py .\evaluate_crack_detection.py --limit 8

# Réentraîner le réseau après avoir validé un nouveau lot (environ une heure)
& $py .\train_crack_unet.py --steps 3000

# Tests
& $py -m unittest discover

# Tests navigateur (Chrome requis), sur des copies de la base et un cache à part
& $py .\validation\validate_analysis_ui.py
& $py .\validation\validate_editing_ui.py
& $py .\validation\validate_zoom_ui.py
```

Aucun réglage de la détection ne devrait être retenu sans une mesure avant et
après sur le banc. Et pour savoir ce que vaut vraiment un nouveau modèle,
l'entraîner en réservant des tuiles puis l'évaluer sur celles-là seulement —
sinon le banc mesure la performance sur les tuiles mêmes qui ont servi à
l'apprentissage, et surestime d'environ 6 points de F1 :

```powershell
& $py .\train_crack_unet.py --exclude-zones 6 11 14 19 22 --output candidat.pt
& $py .\evaluate_crack_detection.py --model candidat.pt --zones 6 11 14 19 22
```

## Dépendances

Installées automatiquement par le lanceur : `requirements_annotation_app.txt`
dit quoi, `constraints_annotation_app.txt` en fixe les versions exactes, celles
du poste d'origine — un autre numpy ou un autre torch peut déplacer une
proposition de détection de quelques pixels. Modifier l'un de ces deux
fichiers déclenche une mise à jour au lancement suivant.

`torch` (version CPU) sert au réseau de segmentation ; sans lui l'application
démarre quand même et reprend le modèle par pixel, nettement moins bon.
