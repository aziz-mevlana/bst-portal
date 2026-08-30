# BST Portal - Windows kurulum ve calistirma

## Hazir durum

Proje Python 3.12 ve proje icindeki `.venv` sanal ortami ile calisacak sekilde ayarlanmistir. Sisteminizdeki diger Python projelerinin kutuphaneleri etkilenmez.

## Calistirma

1. Proje klasorundeki `start_windows.bat` dosyasina cift tiklayin.
2. Terminalde `Starting development server` mesaji gorundugunde tarayicidan `http://127.0.0.1:8000/` adresini acin.
3. Sunucuyu kapatmak icin terminalde `Ctrl+C` tuslarina basin.

Sanal ortam silinirse veya proje baska bir Windows bilgisayara tasinirsa `setup_windows.ps1` dosyasini PowerShell ile bir kez calistirin. PowerShell betik calistirmayi engellerse proje klasorunde su komutu kullanin:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

## Ortam ayarlari

Yerel ayarlar `.env` dosyasindan okunur. E-posta gonderimi icin `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` ve `DEFAULT_FROM_EMAIL` alanlarini doldurun. Gmail kullaniyorsaniz normal hesap sifresi yerine iki adimli dogrulama ile uretilen uygulama sifresini kullanin. Gemini ozelligi icin `GEMINI_API_KEY` alanini doldurun. Bu servis anahtarlari olmadan ana portal calisir; yalnizca ilgili harici servis ozelligi kullanilamaz. Anahtar eklendikten sonra sunucuyu kapatip yeniden baslatin.

Canli ortama cikarken `DJANGO_SECRET_KEY` degerini rastgele ve gizli bir anahtarla degistirin, `DJANGO_DEBUG=False` yapin ve `DJANGO_ALLOWED_HOSTS` alanina gercek alan adini yazin.

## Elle kullanilabilecek komutlar

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```
