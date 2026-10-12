<#
    Ouvre une fenetre de selection, puis lance l'application sur l'image
    choisie. Equivalent de `.\run_annotation_app.ps1 -Choisir`.

    Rouvrir une mosaique deja annotee retrouve son travail. Ouvrir une image
    nouvelle part d'une grille vierge, sans toucher aux autres.

        .\choisir_image.ps1
        .\choisir_image.ps1 -Port 8001        # un second serveur en parallele
#>
param(
    [int] $Port = 8000,
    [string] $Database
)

$arguments = @{ Choisir = $true; Port = $Port }
if ($Database) { $arguments.Database = $Database }
& (Join-Path $PSScriptRoot "run_annotation_app.ps1") @arguments
