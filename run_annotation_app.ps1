<#
    Lance l'application, sur n'importe quel poste et depuis n'importe quel
    dossier. Rien a configurer :

    - au premier lancement, l'environnement Python est cree dans `.venv`, a
      cote de ce script, avec les versions exactes du poste d'origine
      (quelques minutes, environ 1 Go) ;
    - l'image ouverte est la derniere utilisee sur ce poste ; la premiere fois,
      une fenetre demande de la choisir ;
    - le navigateur s'ouvre tout seul quand le serveur est pret.

        .\run_annotation_app.ps1
        .\run_annotation_app.ps1 -Choisir              # changer d'image
        .\run_annotation_app.ps1 -Image "D:\MEB\mosaique.tif"
        .\run_annotation_app.ps1 -Partager             # ouvrir aux autres postes

    L'identifiant qui separe les annotations d'une mosaique de celles d'une
    autre est deduit du fichier : une mosaique deja connue retrouve son
    travail, meme deplacee ; une image nouvelle part d'une grille vierge, meme
    si elle porte le nom d'une autre. `-ImageId` force cet identifiant ; le
    serveur refuse qu'il soit deja celui d'une autre image.

    -Database ecrit dans une base separee : c'est la facon de repartir de zero
    sur une image deja annotee, ou de ne rien melanger.
#>
param(
    [string] $Image,
    [switch] $Choisir,
    [string] $ImageId,
    [string] $Database,
    [int] $Port = 8000,
    [switch] $Partager,
    [switch] $SansNavigateur
)

$ErrorActionPreference = "Stop"

$projectDirectory = $PSScriptRoot
$parentDirectory = Split-Path -Parent $projectDirectory
# Les chemins relatifs passes en argument se comprennent depuis le dossier du
# projet, et non depuis le repertoire courant de l'appelant.
Set-Location -LiteralPath $projectDirectory


# --- 1. Environnement Python ------------------------------------------------

$requirements = Join-Path $projectDirectory "requirements_annotation_app.txt"
$constraints = Join-Path $projectDirectory "constraints_annotation_app.txt"
$localEnvironment = Join-Path $projectDirectory ".venv"
$stampFile = Join-Path $localEnvironment "fissures-installation.txt"

function Test-PythonEnvironment([string] $python) {
    # Un `.venv` copie depuis un autre poste existe mais ne marche pas : ses
    # chemins internes sont absolus. On essaie donc vraiment d'importer.
    $ErrorActionPreference = "Continue"
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    & $python -c "import fastapi, uvicorn, numpy, scipy, skimage, sklearn, PIL, joblib, matplotlib" 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-InstallationStamp {
    ((Get-FileHash -LiteralPath $requirements).Hash + (Get-FileHash -LiteralPath $constraints).Hash)
}

function Find-BasePython {
    # Python 64 bits, de 3.10 a 3.13 ; 3.12 de preference, la version du
    # poste d'origine. Sans guillemets dans le code passe a Python : Windows
    # PowerShell 5.1 les mutile en route.
    $ErrorActionPreference = "Continue"
    $probe = "import sys; print(sys.executable if (3,10) <= sys.version_info[:2] <= (3,13) and sys.maxsize > 2**32 else 0)"
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in "3.12", "3.13", "3.11", "3.10") { $candidates += , @("py", "-$version") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @("python") }
    foreach ($candidate in $candidates) {
        $arguments = @($candidate | Select-Object -Skip 1) + @("-c", $probe)
        $output = & $candidate[0] @arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $output -and "$($output | Select-Object -Last 1)".Trim() -ne "0") {
            return "$($output | Select-Object -Last 1)".Trim()
        }
    }
    return $null
}

function Install-LocalEnvironment {
    $ErrorActionPreference = "Continue"
    $venvPython = Join-Path $localEnvironment "Scripts\python.exe"
    if (-not (Test-PythonEnvironment $venvPython) -and (Test-Path -LiteralPath $localEnvironment)) {
        # Environnement casse (copie d'un autre poste, installation coupee) :
        # on repart de zero plutot que de rapiecer.
        Write-Host "Environnement .venv inutilisable sur ce poste : il est recree."
        Remove-Item -LiteralPath $localEnvironment -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $basePython = Find-BasePython
        if (-not $basePython) {
            throw ("Aucun Python 64 bits de 3.10 a 3.13 sur ce poste.`n" +
                   "Installer Python 3.12 (python.org, ou le catalogue logiciel du labo), " +
                   "puis relancer.")
        }
        Write-Host ""
        Write-Host "Premiere utilisation sur ce poste : installation de l'environnement Python." -ForegroundColor Cyan
        Write-Host "Quelques minutes, environ 1 Go, une seule fois. Python utilise : $basePython"
        Write-Host ""
        # `Out-Host` : sans lui, la sortie se melerait a la valeur rendue.
        & $basePython -m venv $localEnvironment | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Creation de l'environnement impossible dans $localEnvironment" }
    }
    & $venvPython -m pip install --disable-pip-version-check `
        -r $requirements -c $constraints `
        --extra-index-url https://download.pytorch.org/whl/cpu | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw ("Installation des dependances impossible (voir les messages de pip ci-dessus).`n" +
               "Derriere un proxy, definir HTTPS_PROXY avant de relancer, par exemple :`n" +
               "  `$env:HTTPS_PROXY = 'http://proxy.exemple:8080'")
    }
    Set-Content -LiteralPath $stampFile -Value (Get-InstallationStamp) -Encoding ASCII
    return $venvPython
}

$pythonExecutable = Join-Path $localEnvironment "Scripts\python.exe"
$upToDate = (Test-Path -LiteralPath $stampFile) -and
    ((Get-Content -LiteralPath $stampFile -Raw).Trim() -eq (Get-InstallationStamp))
if (-not ($upToDate -and (Test-PythonEnvironment $pythonExecutable))) {
    # Sur le poste d'origine, l'environnement historique est un cran au-dessus.
    # On le reprend s'il fonctionne, plutot que d'en installer un second.
    $legacyPython = Join-Path $parentDirectory ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $localEnvironment) -and (Test-PythonEnvironment $legacyPython)) {
        $pythonExecutable = $legacyPython
    }
    else {
        $pythonExecutable = Install-LocalEnvironment
    }
}


# --- 2. Image ---------------------------------------------------------------

function Read-RecordedImage([string] $record) {
    if (-not (Test-Path -LiteralPath $record)) { return $null }
    $recorded = "$(Get-Content -LiteralPath $record -Raw -Encoding UTF8)".Trim()
    if ($recorded -and (Test-Path -LiteralPath $recorded)) { return $recorded }
    return $null
}
# Derniere image ouverte sur ce poste, et mosaique de reference eventuelle.
# Toutes deux sont notees dans annotation_app\data\, hors du depot : le code ne
# contient aucun nom d'echantillon.
$lastImage = Read-RecordedImage (Join-Path $projectDirectory "annotation_app\data\derniere_image.txt")
$referenceImage = $env:CRACK_REFERENCE_IMAGE
if (-not ($referenceImage -and (Test-Path -LiteralPath $referenceImage))) {
    $referenceImage = Read-RecordedImage (Join-Path $projectDirectory "annotation_app\data\image_reference.txt")
}

function Select-Image {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Choisir la mosaique a annoter"
    $dialog.Filter = "Images TIFF (*.tif;*.tiff)|*.tif;*.tiff|Tous les fichiers (*.*)|*.*"
    $dialog.Multiselect = $false
    foreach ($folder in @(
            $(if ($lastImage) { Split-Path -Parent $lastImage }),
            (Join-Path $projectDirectory "images"),
            $(if ($referenceImage) { Split-Path -Parent $referenceImage }),
            [Environment]::GetFolderPath("MyDocuments"))) {
        if ($folder -and (Test-Path -LiteralPath $folder)) { $dialog.InitialDirectory = $folder; break }
    }
    # Une fenetre proprietaire au premier plan : lancee depuis VS Code, la
    # boite de dialogue s'ouvrait sinon derriere l'editeur.
    $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
    try {
        if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { return $dialog.FileName }
        return $null
    }
    finally { $owner.Dispose() }
}

if (-not $Image -and -not $Choisir) {
    if ($lastImage) { $Image = $lastImage }
    elseif ($referenceImage) { $Image = $referenceImage }
}
if (-not $Image) {
    Write-Host "Choisir la mosaique dans la fenetre qui s'ouvre..."
    $Image = Select-Image
    if (-not $Image) { Write-Host "Aucune image choisie, rien n'est lance."; return }
}
if (-not (Test-Path -LiteralPath $Image)) { throw "Image introuvable : $Image" }
$Image = (Resolve-Path -LiteralPath $Image).Path


# --- 3. Port et adresse -----------------------------------------------------

function Test-PortBusy([int] $candidate) {
    [bool](Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)
}
$requestedPort = $Port
while ((Test-PortBusy $Port) -and $Port -lt $requestedPort + 20) { $Port++ }
if (Test-PortBusy $Port) { throw "Aucun port libre entre $requestedPort et $Port." }
if ($Port -ne $requestedPort) { Write-Host "Port $requestedPort deja pris : utilisation du port $Port." }

# Par defaut, l'application n'ecoute que ce poste. `-Partager` l'ouvre au
# reseau ; sur un poste gere, encore faut-il que le pare-feu le permette.
$hostAddress = if ($Partager) { "0.0.0.0" } else { "127.0.0.1" }


# --- 4. Lancement -----------------------------------------------------------

# Ces variables ne valent QUE pour ce lancement. Les poser sans les remettre
# comme avant les laissait dans la session : un lancement suivant reprenait
# alors l'image precedente. On note donc l'etat d'origine pour le restaurer a
# la sortie, et on repart d'une ardoise vide.
$previousEnvironment = @{}
foreach ($name in "CRACK_IMAGE_PATH", "CRACK_IMAGE_ID", "CRACK_DATABASE_PATH") {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
    Set-Item -Path "Env:$name" -Value "" -ErrorAction SilentlyContinue
}
$env:CRACK_IMAGE_PATH = $Image
if ($ImageId) { $env:CRACK_IMAGE_ID = $ImageId }
if ($Database) { $env:CRACK_DATABASE_PATH = $Database }

Write-Host ""
Write-Host "Application     : http://127.0.0.1:$Port"
if ($Partager) {
    # Un poste a souvent plusieurs reseaux : le domaine du laboratoire, un
    # VPN, un Wi-Fi. On les liste tous, avec le nom du reseau.
    $profiles = @{}
    foreach ($item in (Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
        $profiles[$item.InterfaceAlias] = $item.Name
    }
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $profiles.ContainsKey($_.InterfaceAlias)
        })
    foreach ($item in $addresses) {
        Write-Host ("Acces equipe    : http://{0}:{1}   ({2})" -f $item.IPAddress, $Port, $profiles[$item.InterfaceAlias])
    }
    if (-not $addresses) { Write-Host "Acces equipe    : aucune adresse reseau utilisable" }

    # Encore faut-il interroger le bon pare-feu. Sur les postes geres, la
    # strategie de groupe desactive souvent celui de Windows au profit d'un
    # autre logiciel de securite, gere par l'informatique : y ajouter une
    # regle n'a alors aucun effet, et seule l'informatique peut ouvrir le port.
    $categories = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object {
        if ("$($_.NetworkCategory)" -eq "DomainAuthenticated") { "Domain" } else { "$($_.NetworkCategory)" }
    })
    $windowsFirewall = [bool](Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction SilentlyContinue |
        Where-Object { "$($_.Enabled)" -eq "True" -and $categories -contains $_.Name })
    if (-not $windowsFirewall) {
        $product = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct -ErrorAction SilentlyContinue |
            ForEach-Object { $_.displayName }) -join ", "
        if (-not $product) { $product = "un autre logiciel" }
        Write-Host ""
        Write-Host "Partage         : le pare-feu Windows est desactive sur ce poste ;" -ForegroundColor Yellow
        Write-Host "                  les connexions entrantes sont filtrees par $product."
        Write-Host "                  Si un collegue ne peut pas se connecter, seule l'informatique"
        Write-Host "                  peut ouvrir le port TCP $Port. Test depuis son poste :"
        foreach ($item in $addresses) {
            Write-Host ("                    Test-NetConnection {0} -Port {1}" -f $item.IPAddress, $Port)
        }
    }
    else {
        $allowed = $false
        try {
            $allowed = [bool](Get-NetFirewallPortFilter -ErrorAction Stop |
                Where-Object { $_.Protocol -eq "TCP" -and $_.LocalPort -eq "$Port" } |
                Get-NetFirewallRule -ErrorAction SilentlyContinue |
                Where-Object { $_.Enabled -eq "True" -and $_.Direction -eq "Inbound" -and $_.Action -eq "Allow" })
        } catch { }
        if (-not $allowed) {
            Write-Host ""
            Write-Host "Partage         : aucune regle de pare-feu n'ouvre le port $Port." -ForegroundColor Yellow
            Write-Host "                  Dans un PowerShell ADMINISTRATEUR, une seule fois :"
            Write-Host ("                  New-NetFirewallRule -DisplayName 'Fissures (port {0})' ``" -f $Port)
            Write-Host ("                    -Direction Inbound -Action Allow -Protocol TCP ``")
            Write-Host ("                    -LocalPort {0} -Profile Domain" -f $Port)
        }
    }
    Write-Host ""
}
Write-Host "Image           : $Image"
if ($env:CRACK_IMAGE_ID) { Write-Host "Identifiant     : $env:CRACK_IMAGE_ID" }
if ($env:CRACK_DATABASE_PATH) { Write-Host "Base            : $env:CRACK_DATABASE_PATH" }
else { Write-Host "Base            : annotation_app\data\annotations.sqlite3" }
if ($env:CRACK_BACKUP_DIR) { Write-Host "Sauvegardes     : $env:CRACK_BACKUP_DIR" }
else { Write-Host "Sauvegardes     : annotation_app\data\sauvegardes (CRACK_BACKUP_DIR pour un autre disque)" }
Write-Host "Python          : $pythonExecutable"
Write-Host "Arret           : Ctrl+C dans ce terminal"
Write-Host ""

# Le navigateur ne s'ouvre qu'une fois le serveur pret : le chargement du
# reseau de reperage prend quelques secondes, plus au premier lancement.
$address = "http://127.0.0.1:$Port"
$browser = $null
if (-not $SansNavigateur) {
    $browser = Start-Job -ScriptBlock {
        param($url, $portNumber)
        for ($attempt = 0; $attempt -lt 240; $attempt++) {
            $client = New-Object System.Net.Sockets.TcpClient
            try { $client.Connect("127.0.0.1", $portNumber); Start-Process $url; return }
            catch { Start-Sleep -Milliseconds 500 }
            finally { $client.Dispose() }
        }
    } -ArgumentList $address, $Port
}

try {
    & $pythonExecutable -m uvicorn annotation_app.main:app --host $hostAddress --port $Port
}
finally {
    if ($browser) {
        Stop-Job $browser -ErrorAction SilentlyContinue
        Remove-Job $browser -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in $previousEnvironment.Keys) {
        Set-Item -Path "Env:$name" -Value $previousEnvironment[$name] -ErrorAction SilentlyContinue
    }
}
