$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host 'BST Portal Windows kurulumu baslatiliyor...' -ForegroundColor Cyan

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    }
    else {
        throw 'Python bulunamadi. Python 3.12 kurup komutu yeniden calistirin.'
    }
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    $secret = & $python -c "import secrets; print(secrets.token_urlsafe(50))"
    $envContent = Get-Content '.env' -Raw
    $envContent = $envContent.Replace(
        'django-insecure-replace-this-with-a-random-secret',
        $secret
    )
    Set-Content '.env' -Value $envContent -Encoding utf8
    Write-Host '.env dosyasi .env.example uzerinden olusturuldu.' -ForegroundColor Yellow
}

& $python manage.py migrate --noinput
& $python manage.py check

Write-Host ''
Write-Host 'Kurulum tamamlandi.' -ForegroundColor Green
Write-Host 'Uygulamayi baslatmak icin start_windows.bat dosyasini acin.'
