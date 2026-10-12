<#
    Prepare une copie du projet a donner a un collegue (cle USB, disque).

    Copie le code et les modeles de detection, mais PAS l'etat de ce poste :
    environnement Python (il ne fonctionnerait pas ailleurs), cache d'analyse
    (plusieurs Go, lie aux chemins de ce poste), sauvegardes, base de travail.
    Le collegue ouvre ensuite le dossier dans VS Code et lance l'application ;
    le premier lancement installe tout seul l'environnement Python.

        .\preparer_copie.ps1 -Destination E:\
        .\preparer_copie.ps1 -Destination E:\ -AvecAnnotations
        .\preparer_copie.ps1 -Destination E:\ -Image "D:\MEB\mosaique.tif"

    -AvecAnnotations joint une copie de la base : le collegue part alors du
    travail deja fait. Ses annotations vivront ensuite dans sa copie, sans
    retour automatique vers celle-ci.

    -Image joint une ou plusieurs mosaiques, dans `images\` : c'est la que la
    fenetre de choix s'ouvre en premier.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Destination,
    [switch] $AvecAnnotations,
    [string[]] $Image
)

$ErrorActionPreference = "Stop"
$source = $PSScriptRoot
Set-Location -LiteralPath $source
if (-not (Test-Path -LiteralPath $Destination)) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
}
$target = Join-Path (Resolve-Path -LiteralPath $Destination).Path (Split-Path -Leaf $source)

Write-Host "Copie du code vers $target"
# /XD exclut tout dossier de ce nom : `data` est l'etat du poste
# (annotation_app\data), `sorties` celui des tests navigateur.
robocopy $source $target /E /XD .venv __pycache__ .test-temp data sorties .git /XF *.pyc /NFL /NDL /NJH /NP | Out-Host
if ($LASTEXITCODE -ge 8) { throw "La copie a echoue (robocopy, code $LASTEXITCODE)." }

if ($AvecAnnotations) {
    $database = Join-Path $source "annotation_app\data\annotations.sqlite3"
    if (-not (Test-Path -LiteralPath $database)) { throw "Aucune base a copier : $database" }
    $python = @((Join-Path $source ".venv\Scripts\python.exe"),
                (Join-Path (Split-Path -Parent $source) ".venv\Scripts\python.exe")) |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) { throw "Python introuvable : lancer l'application une fois sur ce poste." }
    $copy = Join-Path $target "annotation_app\data\annotations.sqlite3"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $copy) | Out-Null
    if (Test-Path -LiteralPath $copy) { throw "Une base existe deja dans la destination : $copy" }
    # Par l'API de sauvegarde de SQLite : coherent meme si le serveur tourne.
    & $python -c "import sqlite3, sys; source = sqlite3.connect(sys.argv[1]); copy = sqlite3.connect(sys.argv[2]); source.backup(copy); copy.close()" $database $copy
    if ($LASTEXITCODE -ne 0) { throw "Copie de la base impossible." }
    Write-Host "Annotations     : copiees"
}

foreach ($item in $Image) {
    if (-not (Test-Path -LiteralPath $item)) { throw "Image introuvable : $item" }
    $images = Join-Path $target "images"
    New-Item -ItemType Directory -Force -Path $images | Out-Null
    Write-Host "Copie de l'image $(Split-Path -Leaf $item) (cela peut prendre une minute)..."
    Copy-Item -LiteralPath $item -Destination $images
}

$size = (Get-ChildItem -LiteralPath $target -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ""
Write-Host ("Copie prete : {0} ({1:N0} Mo)" -f $target, $size) -ForegroundColor Green
Write-Host "Chez le collegue : ouvrir ce dossier dans VS Code, puis Ctrl+Maj+B."
Write-Host "Ou double-cliquer sur Lancer.cmd. Il faut Python 3.10 a 3.13 installe."
