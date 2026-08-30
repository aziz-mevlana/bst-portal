# BST Portal UI/UX Düzeltme ve Entegrasyon Raporu

Tarih: 20 Ağustos 2026

Bu çalışma yeni bir ürün özelliği eklemek yerine mevcut bildirim, dashboard, proje formu, profil bağlantıları ve yönetim arayüzlerini tamamlamak ve tutarlı hâle getirmek için yapıldı. Mevcut rol, permission, mezun, ekip, beğeni, haber ve moderasyon altyapıları korunmuştur.

## Düzeltilenler

- Navbar bildirim alanı gerçek bir SVG çan butonu ve çalışan dropdown olarak tamamlandı.
- Bildirim tetikleyicisi tek parça 40 × 40 px kontrol hâline getirildi. Okunmamış sayı artık alt satırda metin olarak değil, çanın sağ üstünde 18 px yuvarlak badge olarak gösteriliyor. `0` değeri render edilmiyor.
- Arama, bildirim ve profil kontrolleri aynı dikey merkeze alındı. Badge, buton hit area’sını veya navbar yüksekliğini değiştirmiyor.
- Bildirim dropdown’ı sayfa değiştirmeden açılıyor; dışarı tıklama ve `Escape` ile kapanıyor. `Escape` sonrasında klavye odağı çan butonuna dönüyor.
- Bir bildirim POST isteğiyle okundu işaretlenip güvenli uygulama içi hedefine yönleniyor. “Tümünü okundu yap” JavaScript ile anlık badge güncelliyor; JavaScript olmadığında normal POST geri dönüşü korunuyor.
- Bildirim CSS dosyasının cache sürümü `20260820.1` olarak yükseltildi; tarayıcının eski navbar stilini göstermesi engellendi.
- Yönetim ana sayfası sadeleştirildi; tekrar eden kartlar ve navigasyon tekrarları kaldırıldı.
- Sidebar yetkilere dokunulmadan içerik, kullanıcılar, moderasyon ve kurumsal gruplarına ayrıldı. Emoji yerine mevcut SVG ikon dili kullanıldı.
- Yeni eklenen kullanıcı metinlerinde görünen İngilizce ifadeler Türkçeleştirildi.
- Proje oluşturma ve düzenleme ekranları genel proje bağlantısı, GitHub repository path’i ve çoklu proje görselleriyle aynı akış içinde bağlandı.
- Windows’ta mevcut bir proje görseli yeniden doğrulanırken açık kalabilen dosya tutamacı kapatıldı. Bu sayede medya testi ve geçici klasör temizliği güvenilir hâle geldi.

## Dashboard

Üst alanda yalnızca dört ana KPI bırakıldı:

- Öğrenciler
- Projeler
- Mezunlar
- Bekleyen İşlemler

Yapılan sadeleştirmeler:

- Aktif kullanıcı, BST Yetkilisi, akademisyen, aktif proje, tamamlanan proje, site incelemesi, mezun talebi, iş birliği ve haber onayı gibi çok sayıdaki ayrı üst kart kaldırıldı.
- Moderasyon, site incelemesi, mezun talebi, iş birliği talebi ve haber onayı tek “Bekleyen İşlemler” alanında birleştirildi.
- Bekleyen iş bulunmadığında sade bir empty state gösteriliyor.
- Alt bölümde üst KPI’ları tekrar eden Öğrenciler / Projeler / Bekleyen Onay / Mezunlar kartları kaldırıldı.
- Sidebar’daki bağlantıları tekrar eden “Hızlı Erişim” bölümü kaldırıldı.
- Sınıf dağılımı korundu ve kompakt bar görünümüne getirildi.
- Aktif / tamamlanan proje dağılımı daha küçük ve okunabilir hâle getirildi.
- Teknoloji ve kategori verileri tek “Proje Analitiği” kartında toplandı.
- `AI_ANSWER` ve `PROFILE_VIEW` gibi internal anahtarlar yerine Türkçe kullanıcı etiketleri gösteriliyor.
- “Son Aktiviteler” artık sayaç cümleleri üretmiyor; gerçek `AuditLog` olaylarını gösteriyor. Kayıt yoksa sahte veri yerine empty state kullanılıyor.
- Dashboard sayaçları merkezi `dashboard_statistics()` servisi üzerinden üretiliyor.

Veritabanı ile doğrulanan merkezi sayaçlar:

| Sayaç | Değer |
|---|---:|
| Öğrenci | 1 |
| BST Yetkilisi | 1 |
| Akademisyen | 4 |
| Mezun | 405 |
| Proje | 1 |
| Aktif proje | 0 |
| Tamamlanan proje | 1 |
| Bekleyen işlem | 0 |
| Ekip | 0 |

## UI

- Yönetim sidebar’ı başlıklarla gruplandırıldı; permission koşulları korunarak sadece yetkili menüler render ediliyor.
- Site incelemeleri, mezun talepleri ve iş birliği gibi alanlarda emoji kaldırıldı, tutarlı SVG ikonlar kullanıldı.
- Ekip formundaki etiketler “Ekip Adı”, “Açıklama”, “Teknolojiler”, “Çalışma Alanları” ve “Üye Alımı Açık” olarak Türkçeleştirildi.
- AI ekranları ve hesap akışlarında kalan görünür İngilizce metinler/bozuk Türkçe ifadeler temizlendi; “Email” yerine “E-posta” kullanımı tutarlılaştırıldı.
- Proje paylaşım kartında LinkedIn, X ve bağlantı kopyalama için SVG ikonlu kontroller eklendi.
- Profil bağlantıları GitHub, LinkedIn ve onaylı kişisel web sitesi için platform/globe SVG ikonlarıyla düzenlendi.
- Kullanıcı tarafından girilen dış bağlantılarda mevcut güvenli URL üretimi ve `noopener noreferrer nofollow ugc` davranışı korundu.
- Ortak koyu tema, hover ve `focus-visible` davranışlarıyla uyum sağlandı.

## Proje Formu

Yeni proje oluşturma ve proje düzenleme sayfalarında şu alanlar doğrudan kullanılabiliyor:

- **Proje Bağlantısı:** Canlı demo, proje sitesi veya genel proje URL’si oluşturma sırasında eklenebiliyor; düzenlemede değiştirilebiliyor veya kaldırılabiliyor.
- **GitHub Repository:** Sabit `github.com/` prefix’i yanında yalnızca `owner/repository` değeri alınıyor. Alan isteğe bağlı; tam URL girilirse doğrulama hatası veriyor. Düzenlemede ekleme, değiştirme ve kaldırma destekleniyor.
- **Proje Görselleri:** Çoklu görsel oluşturma akışında kaydediliyor. Görsellerle proje aynı transaction içinde işleniyor ve seçilen görsel kapak oluyor.
- Düzenleme ekranında mevcut görseller listeleniyor; yeni görsel eklenebiliyor, kapak değiştirilebiliyor ve onaylı silme yapılabiliyor.
- Kapak görseli silinirse sıradaki proje görseli otomatik kapak yapılıyor.
- Proje, repository ve görsel işlemleri için audit kayıtları korunuyor.

Regression testleri; oluşturma, düzenleme, bağlantı/repository kaldırma, çoklu görsel, tek kapak ve kapak silindikten sonra yeni kapak seçimini kapsıyor.

## Bildirim

Navbar davranışı:

1. Arama kontrolü, 40 px bildirim butonu ve profil kontrolü aynı satırda/dikey merkezde duruyor.
2. SVG çan ve sayı aynı `button` içindedir; badge ayrı link veya buton değildir.
3. Okunmamış bildirim varsa sağ üstte badge görünür; bildirim yoksa badge DOM’a eklenmez.
4. Butonun tamamı tıklanabilir; yalnız küçük SVG tıklama hedefi olarak kullanılmaz.
5. Dropdown açıldığında URL değişmez ve son 10 bildirim okunmuş/okunmamış ayrımıyla gösterilir.
6. Dışarı tıklama ve `Escape` ile kapanır; `aria-expanded` güncellenir.
7. “Tümünü okundu yap” sonrasında masaüstü badge’i ve mobil sayaç anlık temizlenir.
8. 360 px mobil görünümde dropdown soldan/sağdan 12 px boşlukla tamamen ekran içinde kalır.

Tarayıcı ölçümleri:

| Kontrol | Masaüstü | Mobil |
|---|---:|---:|
| Bildirim butonu | 40 × 40 px | 40 × 40 px |
| Badge | 18 × 18 px | 18 × 18 px |
| Dikey merkez | Arama 33.98 / Bildirim 33.98 / Profil 33.99 px | Bildirim 34 / Menü 34 px |
| Yatay overflow | Yok | Yok |
| Mobil dropdown | — | 326 px; 12–338 px sınırlarında |

Tarayıcı konsolunda error veya warning görülmedi. Dropdown açma, badge, `Escape`, focus dönüşü ve tümünü okundu yap davranışları manuel olarak doğrulandı.

## Değiştirilen Önemli Dosyalar

- `templates/includes/header.html`
- `templates/base.html`
- `static/css/bst-ui-v2.css`
- `static/js/header.js`
- `dashboard/statistics.py`
- `dashboard/views.py`
- `templates/dashboard/base.html`
- `templates/dashboard/home_teacher.html`
- `projects/forms.py`
- `projects/views.py`
- `projects/models.py`
- `templates/projects/project_form.html`
- `templates/projects/project_detail.html`
- `templates/projects/showcase_manage.html`
- `templates/portal/portfolio_detail.html`
- `core/test_notifications_modernization.py`
- `projects/test_modernization.py`

Bu UI/UX turunda yeni model veya migration eklenmedi.

## Veri ve Yedek Güvenliği

- Çalışma öncesi zaman damgalı SQLite yedeği: `backups/pre-ui-polish-20260820-212855.sqlite3`
- Tarayıcı QA’sı üretim verisi yerine geçici SQLite kopyasında yapıldı; geçici kopya test sonunda güvenli biçimde silindi.
- Üretim ve çalışma öncesi yedek karşılaştırmasında içerik tablolarında veri kaybı bulunmadı. Farklar yalnızca giriş oturumuna ait `last_login`, profil `updated_at` ve `django_session` kayıtlarıdır.
- Korunan temel kayıtlar: 7 kullanıcı, 405 mezun, 1.128 iş deneyimi, 4 akademisyen, 1 proje, 51 teknoloji ve 21 kategori.

## Testler

```text
Passed: 162
Failed: 0
Skipped: 0
```

Ek doğrulamalar:

```text
python manage.py check: Hata yok (0 silenced)
makemigrations --check --dry-run: No changes detected
migrate --check: Başarılı, bekleyen migration yok
collectstatic --dry-run --noinput: Başarılı
pip check: No broken requirements found
Navbar bildirim regression testleri: 4/4 geçti
```

Manuel responsive QA; bildirim dropdown, dashboard, sidebar, ekip formu, proje oluşturma, proje düzenleme, proje detay paylaşımı ve profil bağlantıları için 360/768/1440 px genişliklerde yapıldı. Kontrol edilen ekranlarda yatay overflow görülmedi.

Bu turun tanımlı UI/UX kapsamından eksik bırakılan frontend, backend veya test maddesi bulunmuyor.
