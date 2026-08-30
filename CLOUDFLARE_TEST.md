# Geçici Cloudflare testi

Başlat: proje klasöründe PowerShell ile `./start_cloudflare.ps1`.
Durdur: `./stop_cloudflare.ps1`.
Güncel bağlantı `.preview/url.txt` dosyasındadır. Yeniden başlatmada bağlantı değişir.

- Bilgisayar açık, internete bağlı ve uyku moduna geçmemiş olmalı.
- Bağlantı herkese açıktır; yalnızca güvendiğiniz test ekibiyle paylaşın.
- İlk başlatmada mevcut SQLite veritabanı ve medya `.preview/` içine kopyalanır.
  Test değişiklikleri bu kopyada kalır; asıl veriler değişmez. Yeniden başlatma
  test kopyasını korur, asıl sitedeki sonraki değişiklikleri yeniden kopyalamaz.
- Mevcut kullanıcı hesapları kullanılabilir. Ayrı oturum anahtarı nedeniyle
  yeniden giriş gerekir.
- E-posta ve Gemini ayarları yerel `.env` dosyasından kullanılır. Kayıt ve şifre
  sıfırlama gerçek e-posta gönderebilir; AI kullanımı mevcut API kotasını tüketir.
- DEBUG kapalıdır. Yalnızca verilen Cloudflare alan adı kabul edilir. HTTPS,
  CSRF ve güvenli çerezler açıktır. Arama motorlarına indekslememeleri bildirilir;
  bu bildirim erişim kontrolü değildir.
- Bu, kalıcı hosting değildir. Cloudflare Quick Tunnel için kesintisiz çalışma
  garantisi yoktur; SSE desteklenmez. Geçici testten sonra tüneli durdurun.

Windows sunucusu `.venv` içindeki Waitress 3.0.2'yi kullanır. Eksikse
`./.venv/Scripts/python.exe -m pip install waitress==3.0.2` ile kurulur.
Cloudflared, resmi `cloudflare/cloudflared` GitHub dağıtımından
`.preview/tools/cloudflared.exe` konumuna indirilmiştir.
