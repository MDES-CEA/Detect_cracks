# Analyse de longueur de fissures (images MEB)

Mesure la longueur des fissures sur une image MEB en niveaux de gris, et
sépare la longueur **ouverte** de la longueur **colmatée**.

Le principe : chaque pixel reçoit un coût (faible = ressemble à une fissure,
via un filtre de Sato + obscurité locale), puis le trajet de coût minimal
entre les points d'ancrage suit la fissure au pixel près. Les niveaux de gris
le long du tracé sont ensuite séparés en deux populations (mélange gaussien)
pour distinguer ouvert et colmaté.

Trois scripts, du plus manuel au plus automatique :

| Script | Rôle |
| --- | --- |
| `crack_length_analysis_multi.py` | **Principal.** N fissures, N points d'ancrage chacune, placés à la souris. Gère jonctions, branches et boucles. |
| `crack_length_analysis_auto.py` | Détecte les points d'ancrage tout seul (seuillage + squelettisation), puis réutilise tout l'aval du script principal. |
| `crack_length_analysis.py` | Première version, topologie figée à 4 points. Conservée pour référence. |

---

## 1. Prérequis

- **Python 3.10 ou plus récent** — <https://www.python.org/downloads/>
  Sous Windows, cocher **« Add python.exe to PATH »** pendant l'installation.
- **Git** (seulement pour récupérer le dépôt) — <https://git-scm.com/downloads>
  On peut aussi télécharger le dépôt en ZIP depuis GitHub et sauter Git.
- Un **environnement graphique**. La sélection des points se fait à la souris
  dans une vraie fenêtre : le script ne fonctionne pas sur un serveur sans
  écran, ni dans un notebook (voir « Problèmes courants »).

Sous Linux, installer aussi Tk, qui n'est pas toujours livré avec Python :

```bash
sudo apt install python3-tk        # Debian / Ubuntu
```

---

## 2. Installation

### Le plus simple (Windows)

1. Récupérer le dossier du projet (`git clone …`, ou ZIP décompressé).
2. Double-cliquer sur **`run.bat`**.

Au premier lancement, il crée l'environnement virtuel et installe les
dépendances — compter quelques minutes. Les fois suivantes il démarre
directement. Une fenêtre demande alors l'image à analyser.

### macOS / Linux

```bash
git clone https://github.com/<utilisateur>/<depot>.git
cd <depot>
chmod +x run.sh
./run.sh
```

### Installation manuelle (toutes plateformes)

```bash
git clone https://github.com/<utilisateur>/<depot>.git
cd <depot>

python -m venv .venv                # créer l'environnement virtuel

# activer l'environnement :
.venv\Scripts\activate              # Windows (PowerShell / cmd)
source .venv/bin/activate           # macOS / Linux

pip install -r requirements.txt     # installer les dépendances
```

L'environnement virtuel est à réactiver à chaque nouveau terminal.

---

## 3. Utilisation

### Analyse guidée à la souris (script principal)

```bash
python crack_length_analysis_multi.py mon_image.png
```

Sans argument, une fenêtre de sélection de fichier s'ouvre.

Dans la fenêtre d'image :

| Action | Effet |
| --- | --- |
| **Clic gauche** | Ajoute un point d'ancrage. Le tracé de coût minimal apparaît immédiatement. |
| **Clic droit** ou **Entrée** | Termine la fissure courante, passe à la suivante. |
| **Retour arrière** | Supprime le dernier point. |
| **Échap** | Termine toute la sélection et lance le calcul. |

Une fissure a besoin d'au moins **2 points**. Si le tracé part de travers
(il suit une interface voisine), ajouter un point intermédiaire pour le
forcer à passer au bon endroit — c'est le principal réglage.

Un nouveau clic tombant à moins de 8 px d'un point ou d'un tracé existant
s'y accroche automatiquement : c'est ce qui rend les **jonctions** réellement
communes, donc comptées une seule fois. Une **boucle fermée** se fait en
recliquant sur le premier point de la fissure.

Options :

```bash
--groups "x1,y1;x2,y2" "x3,y3;x4,y4"   # points en ligne de commande, sans clics
--annotations points.json              # rejouer les points d'une analyse précédente
--output-dir resultats/                # dossier de sortie (défaut : celui de l'image)
--show-cost                            # afficher la carte de coût intermédiaire
--show-smoothing                       # comparer tracé brut et tracé lissé, zoomé
--no-show                              # ne pas ouvrir la fenêtre de résultat
```

`--annotations` est le mode le plus utile au quotidien : on clique une fois,
on corrige au besoin le JSON, et on rejoue à l'identique.

### Détection automatique

```bash
python crack_length_analysis_auto.py mon_image.png
```

Options : `--output-dir`, `--no-show`, et `--annotations-only` (écrire
seulement le JSON des points détectés, sans mesurer). Une détection
imparfaite se rattrape ensuite avec :

```bash
python crack_length_analysis_multi.py mon_image.png --annotations mon_image_crack_points.json
```

### Vérifier sur l'exemple fourni

`A4D9CD5C.PNG` est inclus dans le dépôt pour tester l'installation :

```bash
python crack_length_analysis_auto.py A4D9CD5C.PNG
```

---

## 4. Fichiers produits

Pour une image `mon_image.png`, dans le dossier de sortie :

| Fichier | Contenu |
| --- | --- |
| `mon_image_crack_analysis.png` | Image annotée : ouvert en bleu, colmaté en rouge, transition en violet. |
| `mon_image_crack_lengths.csv` | Une ligne par fissure + une ligne `all` : longueurs totale / ouverte / colmatée, % colmaté, longueur brute, moyennes de gris. |
| `mon_image_crack_points.json` | Points d'ancrage, à rejouer avec `--annotations`. |
| `mon_image_auto_detection.png` | (mode auto) étapes de la détection. |
| `mon_image_smoothing_check.png` | (avec `--show-smoothing`) comparaison brut / lissé. |

**Les longueurs sont en pixels.** Pour passer en micromètres, multiplier par
l'échelle de l'image MEB — la conversion n'est pas faite par le script.

Ces fichiers sont ignorés par Git (`.gitignore`) : ils se régénèrent à partir
de l'image.

---

## 5. Réglages

En tête de `crack_length_analysis_multi.py` :

| Constante | Rôle |
| --- | --- |
| `RIDGE_SIGMAS` | Largeurs de fissure recherchées, en pixels (défaut 1 à 7). À adapter si le grossissement change. |
| `PATH_ATTRACTION` | Plus c'est haut, plus le tracé colle aux zones sombres. |
| `SNAP_DISTANCE` | Distance d'accrochage des clics (px). |
| `PATH_SMOOTHING_SIGMA` | Lissage des coordonnées **avant** mesure. Corrige la surestimation en escalier des tracés 8-connexes (jusqu'à +8 % sur une oblique). Le tableau d'erreurs mesurées est en commentaire dans le fichier. |
| `CLASS_SMOOTHING_PIXELS` | Filtre médian sur la classification ouvert/colmaté (impair). |
| `GMM_MIN_*` | Garde-fous : si les deux populations de gris ne sont pas franchement séparées, tout est classé « ouvert » plutôt que coupé arbitrairement. |

Les réglages de la détection automatique sont en tête de
`crack_length_analysis_auto.py`.

---

## 6. Problèmes courants

**« Backend matplotlib non interactif »**
Le script a été lancé dans un notebook ou dans la fenêtre interactive de
VS Code, où `plt.show()` rend la main immédiatement. Le lancer depuis un
**terminal**, ou forcer le backend :

```bash
set MPLBACKEND=TkAgg          # Windows cmd
$env:MPLBACKEND="TkAgg"       # Windows PowerShell
export MPLBACKEND=TkAgg       # macOS / Linux
```

**`ModuleNotFoundError`**
L'environnement virtuel n'est pas activé, ou les dépendances ne sont pas
installées. Réactiver `.venv`, puis `pip install -r requirements.txt`.

**« Aucune fissure sélectionnée »**
La fenêtre a été fermée sans valider. Il faut au moins 2 points par fissure,
puis **Échap** (ou fermer après avoir validé avec Entrée).

**Les clics ne créent pas de points**
Le mode zoom ou déplacement de la barre d'outils matplotlib est actif : il est
volontairement ignoré. Le désactiver en recliquant sur son icône.

**Le tracé passe à côté de la fissure**
Ajouter un point d'ancrage intermédiaire. Si le problème est général,
augmenter `PATH_ATTRACTION` ou ajuster `RIDGE_SIGMAS` à la largeur réelle des
fissures, et vérifier avec `--show-cost`.

---

## 7. Versions de référence

Combinaison utilisée pour la mise au point (Windows 11) :

```
Python 3.14.3
numpy 2.4.4        scipy 1.17.1        scikit-image 0.26.0
scikit-learn 1.9.0 matplotlib 3.10.8   pillow 12.1.1
```

`requirements.txt` fixe des bornes basses, pas ces versions exactes : pip
installera les versions récentes compatibles avec le Python de la machine.
En cas de comportement différent, épingler ces versions-là.
