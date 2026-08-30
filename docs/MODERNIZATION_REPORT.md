# BST Portal kapsamlı modernizasyon teslim raporu

Tarih: 20 Ağustos 2026  
Çalışma dizini: `C:\Users\oguzh\Desktop\bst-portal-main`

## 1. Sonuç özeti

Plan; mevcut SQLite verileri korunarak, yeni migration'lar uygulanarak ve haberler için ayrıca geri alınabilir yedek alınarak tamamlandı. Sistem SQLite üzerinde kalıyor; PostgreSQL bağımlılığı, GitHub API/senkronizasyon kodu ve kalan Celery GitHub zamanlama kaydı kaldırıldı. OAuth, yeni frontend framework veya yeni chat altyapısı eklenmedi.

Son doğrulama sonucu:

- Otomatik testler: **155 passed / 0 failed / 0 skipped**
- `manage.py check`: **0 sorun**
- Migration drift: **yok** (`No changes detected`)
- Bekleyen migration: **yok** (`migrate --check` exit 0)
- Bağımlılık kontrolü: **No broken requirements found**
- Static dry-run: **2 güncel dosya kopyalanabilir, 547 dosya değişmemiş**
- Haber: **63 → 0** (yalnız `Article`; `NewsKeyword` korunmuştur)
- Korunması istenen temel kayıtlar: **eksilme yok**

## 2. Yapılanlar

### 2.1 Hesap, profil ve sosyal bağlantılar

- Sınıf seçimi yalnız `student` ve `staff_student` rollerinde zorunlu hale getirildi; geçerli değerler `1`, `2`, `3`, `4` ile sınırlandı.
- Öğrenci kayıt formuna açık sınıf seçimi eklendi; öğrenci numarasından sınıf türetme kaldırıldı.
- Akademisyen ve mezun profillerindeki sınıf değeri `NULL` olacak şekilde veri ve model davranışı düzenlendi.
- Rol/sınıf uyumu koşullu SQLite constraint ile korunuyor; öğrenci rollerinde `NULL` da açıkça reddediliyor.
- `github_url` yerine doğrulanan `github_username`, `linkedin_url` yerine doğrulanan `linkedin_slug` kullanılıyor.
- GitHub ve LinkedIn public URL'leri saklanan slug/kullanıcı adından property üzerinden üretiliyor.
- Migration yalnız canonical değerleri dönüştürüyor; geçersiz profil varsa veri silmeden kayıt ID'siyle duruyor.
- Hesaba bağlı olmayan 405 mezunun mevcut LinkedIn/GitHub alanları topluca değiştirilmedi.
- Mezun hesabı bağlanırken güvenle ayrıştırılabilen sosyal bilgiler Profile'a kopyalanıyor.
- Kişisel web sitesi için pending/approved/rejected durumları, inceleyen kullanıcı, zaman, standart ret nedeni ve açıklama alanları eklendi.
- Onaylı site URL'si değiştirilince otomatik olarak `pending` oluyor ve public görünümden kalkıyor.
- Website moderasyon geçmişi ekleme-sonrası değiştirilemez kayıtlarla tutuluyor.
- Website doğrulaması HTTP/HTTPS, standart port, public host/IP şartlarını uyguluyor; credentials, localhost, `.local`, private/loopback/link-local/reserved IP ve tehlikeli şemaları reddediyor.
- Kullanıcı kaynaklı dış bağlantılara `noopener noreferrer nofollow ugc` eklendi.
- Public profil rozeti yalnız `staff_student` için “BST Yetkilisi” olarak gösteriliyor.
- `/accounts/profile/` genel ayar sayfası yerine kullanıcının seçtiği projeleri sergileyen profil vitrini haline getirildi; ayrıntılı ayarlar ayrı ayar ekranında tutuluyor.
- Formlara açıklayıcı placeholder metinleri ve zorunlu “Seçiniz” doğrulamaları eklendi.
- Eksik KVKK bağlantısı yerine tam bir KVKK aydınlatma sayfası eklendi.

### 2.2 BST Yetkilisi, moderasyon ve izinler

- Veritabanı rol kodu `staff_student` korundu; görünen rol “BST Yetkilisi” oldu.
- Django Group/Permission tabanlı “BST Yetkilisi” grubu ve migration sonrası otomatik senkronizasyon kuruldu.
- Mevcut ve yeni BST Yetkilileri gruba otomatik ekleniyor; rol değişirse gruptan çıkarılıyor.
- Grup şu güvenli kapsamları alıyor: haber/etkinlik CRUD, rapor ve site inceleme, proje talebi inceleme, iş birliği ilk inceleme ve sınırlandırılmış kullanıcı moderasyonu.
- Aktif oturum sonlandırma ayrı custom permission olarak tanımlandı ve varsayılan gruba verilmedi.
- BST Yetkilisinin admin, superuser, akademisyen veya başka BST Yetkilisini modere etmesi nesne seviyesinde engellendi.
- Hesap kapatma, rol/yetkili atama, akademisyen hesap onayı ve mezun bağlantısı geri alma admin/superuser kapsamında tutuldu.
- Akademisyenlerin mevcut içerik/proje akışları korundu; hesap/site/mezun moderasyon yetkisi otomatik verilmedi.
- Moderasyon nedeni standart kod, açıklama ise ayrı zorunlu alan oldu; eski serbest metinler `other` + açıklama olarak taşındı.
- Askıya alma, yeniden etkinleştirme, fotoğraf kaldırma, oturum sonlandırma, hesap kapatma, site inceleme ve mezun inceleme işlemleri audit/moderasyon kayıtları oluşturuyor.
- Yeni ve kritik mutation endpoint'leri POST + CSRF + sunucu tarafı izin kontrolü kullanıyor; arayüzde confirmation akışları eklendi.
- Kullanıcı moderasyonu ve iş birliği yönetimi, ayrı tasarıma sıçramak yerine yönetim paneli gövdesi içinde açılıyor.

### 2.3 Mezun kayıt talebi

- Public kayda üçüncü rol olarak Mezun eklendi.
- Mezun kişisel e-posta kullanabiliyor; öğrenci/akademisyen kurumsal e-posta kuralı korunuyor. `staff_student` doğrudan public kayıt rolü değildir.
- E-posta doğrulaması sonrası mezun hesabı `is_active=False` ve `pending_review` durumunda oluşturuluyor.
- `AlumniRegistrationRequest`; ad-soyad, yıl, öğrenci numarası, e-posta, durum ve inceleme alanlarını saklıyor.
- `Alumni.student_number` nullable ve boş olmayan değerlerde koşullu unique hale getirildi.
- Yönetim ekranına aramalı mevcut mezun seçimi, maskelenmiş numara ve yalnız yardımcı eşleşme bilgisi eklendi.
- Mevcut mezuna bağlama işlemi `transaction.atomic()` + `select_for_update()` kullanıyor; iş deneyimleri korunuyor ve bağlı kayıt başka hesaba verilemiyor.
- Yeni mezun oluşturma ikinci açık confirmation gerektiriyor.
- Ret işleminde standart neden+açıklama zorunlu; site içi bildirim ve güvenli e-posta sonucu üretiliyor.
- Yanlış bağlantıyı geri alma yalnız admin için ve önceki/yeni ilişki audit metadata'sına yazılıyor.

### 2.4 Proje repository, medya, beğeni, öne çıkarma ve timeline

- `ProjectRepository` yalnız normalize `owner/repository` saklıyor.
- Eski repository/vaka çalışması GitHub URL'leri veri migration ile path'e dönüştürülüyor; geçersiz veya çakışan kayıt varsa migration veri silmeden açık hata veriyor.
- GitHub API çağrıları, sync endpoint/button/task/cache/metrik alanları ve kalan Celery beat girdisi kaldırıldı.
- `project_link` genel demo/proje bağlantısı olarak korundu.
- Proje oluştururken ve düzenlerken çoklu JPG/JPEG/PNG/WEBP yükleme eklendi.
- Görseller gerçek Pillow içeriğiyle doğrulanıyor, dosya başına 5 MB sınırı ve UUID tabanlı ad kullanıyor.
- Video/doküman medya davranışı korundu; 5 MB yalnız proje görselleri için uygulanıyor.
- Proje + ilk görseller tek transaction; DB tek kapak constraint'i ve güvenli kapak değişimi var.
- Oluşturma ve düzenleme ekranlarında yükleme önizlemesi/kapak seçici; mevcut görsellerde kapak yapma ve confirmation ile silme var.
- Detay sayfasına klavye/Escape destekli erişilebilir büyütme diyaloğu eklendi.
- `ProjectLike(project,user)` ve unique constraint, POST like/unlike toggle, görünürlük kontrolü, sayılar ve “En Çok Beğenilen” sıralaması eklendi.
- 10/25/50/100/250/500 eşiklerinde dedupe edilmiş tek seferlik sahip bildirimi uygulanıyor.
- `ProjectFeature`; seçen kullanıcı, açıklama ve audit bilgisi taşıyor. Yalnız akademisyen/admin public+approved projeyi öne çıkarabiliyor.
- Ana sayfadaki sahte “son projeyi öne çıkar” fallback'i kaldırıldı; Öne Çıkan/Çok Beğenilen/Ödüllü bölümleri bağımsız sorgular oldu.
- `ProjectUpdate.note` veri korunarak `description` alanına taşındı; isteğe bağlı `version` ve timeline görünümü eklendi.
- Güncelleme ekleme yetkisi proje sahibi, danışman ve mevcut legacy proje ekip üyeleriyle sınırlandı.

### 2.5 Kurumsal ekip sistemi

- `Team`, `TeamMembership`, `TeamInvitation` ve `TeamOpenRole` modelleri eklendi.
- Ekip adı/slug/açıklama/lider/teknolojiler/çalışma alanları/üye alımı/tarih alanları hazırlandı.
- `Project.team_entity` nullable FK eklendi; mevcut `Project.team` kullanıcı listesi korunuyor.
- Team membership tek başına proje düzenleme yetkisi vermiyor.
- Ekip oluşturucu transaction içinde lider üyelik olarak ekleniyor.
- Başka kullanıcı doğrudan üyeliğe eklenmiyor; liderin pending/accepted/rejected/cancelled davet akışı kullanılıyor.
- Aynı ekip-kullanıcı için duplicate pending davet DB constraint ve servis kontrolüyle engelleniyor.
- Kabul atomik/idempotent; kabulden önce membership oluşmuyor.
- Public ekip listesinde arama, alım durumu, aktif proje, teknoloji, çalışma alanı ve sıralama filtreleri var.
- Ekip detayında üyeler, aktif/tamamlanan projeler, teknolojiler, açık roller ve alım durumu gösteriliyor.
- Proje navigasyonu “Proje Vitrini / Ekipler / İlanlar / Kaydedilenler / Yeni Proje” olarak rol bazlı güncellendi.

### 2.6 Bildirimler

- `Notification` modeline `title` ve koşullu unique `dedupe_key` eklendi.
- Güvenli site içi `target_url`, actor, read timestamp ve son bildirim listesi korundu/genişletildi.
- Ekip, başvuru, yorum, beğeni eşiği, öne çıkarma, site, mezun, moderasyon, danışmanlık ve bekleyen görev tipleri tanımlandı.
- Normal bildirimlerde platform tercihi uygulanıyor; güvenlik/moderasyon ve hesap sonuçları `force=True` ile zorunlu üretilebiliyor.
- Navbar'a sayfa değiştirmeden açılan button tabanlı bildirim dropdown'u, son 10 kayıt ve unread badge eklendi.
- Dışarı tıklama, Escape, `aria-expanded`, odak ve mobil görünüm davranışları eklendi.
- Bildirime gitme önce sahiplik kontrollü POST ile okundu işareti koyuyor; başkasının bildirimi için IDOR engeli var.
- “Tümünü okundu yap” JavaScript ile anlık, JavaScript yokken standart POST redirect ile çalışıyor.

### 2.7 Haber, dashboard ve e-posta

- Pending ve approved haberlerin tümünde checkbox, tekil silme ve toplu silme eklendi.
- Bulk endpoint geçerli ID listesi, transaction, gerçek Article silme sayısı, audit ve merkezi permission policy kullanıyor.
- `clear_development_news --confirm`; `DEBUG=False` veya SQLite dışı veritabanında çalışmayı reddediyor, önce SQLite backup API ile yedek alıyor ve yalnız Article kayıtlarını siliyor.
- Dashboard KPI'ları `dashboard/statistics.py` merkezi servisine taşındı.
- Aktif kullanıcı, bekleyen/aktif/tamamlanan proje, rol dağılımı, mezun ve ilgili modül sayaçları gerçek enum/status alanlarına bağlandı.
- “Bekleyen moderasyon” açık rapor + pending website + pending alumni + pending collaboration toplamı olarak belgelendi.
- Sınıf dağılımı öğrenci ve BST Yetkilisini kapsıyor; kategori/teknoloji ve proje oranları harici grafik kütüphanesi olmadan erişilebilir barlarla gösteriliyor.
- EmailVerification akışındaki yanlış/süresi dolmuş kod, resend cooldown/rate limit ve e-posta değişikliği davranışları korundu/tamamlandı.
- PasswordReset kodları hash'li hale getirildi; mevcut kısa ömürlü düz kodlar migration'da hash'lenip düz metin temizlendi.
- Şifre sıfırlama başlangıcında kayıtlı/kayıtsız e-posta aynı kullanıcı mesajı ve yönlendirmeyi kullanıyor.
- SMTP yalnız `.env` üzerinden okunuyor; `.env.example` Gmail TLS ve uygulama şifresini açıklıyor.
- `python manage.py send_test_email --to adres@example.com` komutu eklendi; eksik credential varsa bağlantı kurmadan anlaşılır hata veriyor.

### 2.8 SQLite ve platform kararı

- Veritabanı SQLite'a sabitlendi; `SQLITE_DATABASE_PATH` ve `SQLITE_TIMEOUT_SECONDS` ayarları eklendi.
- PostgreSQL zorunluluğu, `dj-database-url`, `psycopg2-binary`, PostgreSQL arama dalı ve deployment yönergeleri kaldırıldı.
- SQLite yedek/geri yükleme rehberi güncellendi.
- Mevcut Celery altyapısı yalnız önceden var olan bakım görevleri için korunuyor; GitHub görevi bulunmuyor.

## 3. Değiştirilen önemli dosyalar

- Hesap/model/form/policy: `accounts/models.py`, `accounts/forms.py`, `accounts/views.py`, `accounts/validators.py`, `accounts/roles.py`, `accounts/policies.py`, `accounts/apps.py`
- Mezun iş akışı: `alumni/models.py`, `alumni/services.py`, `dashboard/views.py`
- Proje/ekip: `projects/models.py`, `projects/forms.py`, `projects/views.py`, `projects/team_services.py`, `projects/urls.py`
- Bildirim: `core/models.py`, `core/notifications.py`, `core/views.py`, `core/context_processors.py`
- Haber ve dashboard: `news/views.py`, `dashboard/statistics.py`, `dashboard/views.py`
- E-posta komutları: `accounts/management/commands/send_test_email.py`
- Haber temizleme: `news/management/commands/clear_development_news.py`
- Ana ayarlar/bağımlılıklar: `bst_portal/settings.py`, `.env.example`, `requirements.txt`
- Arayüz: `templates/accounts/`, `templates/alumni/`, `templates/projects/`, `templates/dashboard/`, `templates/core/`, `templates/legal/kvkk.html`, `templates/includes/header.html`
- Frontend davranış/stil: `static/js/header.js`, `static/css/bst-ui-v2.css`
- Operasyon: `docs/OPERATIONS.md`, `DEPLOYMENT_CHECKLIST.md`, `deploy.sh`
- Yeni regresyon testleri: `accounts/test_modernization.py`, `alumni/test_registration_workflow.py`, `career/test_collaboration_permissions.py`, `core/test_notifications_modernization.py`, `dashboard/test_modernization.py`, `projects/test_modernization.py`

## 4. Eklenen migration'lar

- `accounts.0016_websitemoderationhistory_alter_profile_options_and_more`
  - Sosyal slug dönüşümü, website moderasyonu/geçmişi, şifre reset hash dönüşümü, moderasyon nedeni/açıklaması ve rol izinleri.
  - Normalize edilemeyen kritik profil kayıtlarında ID ile fail-fast.
- `accounts.0017_enforce_nonnull_student_class`
  - SQLite'ın `NULL` check davranışını da kapsayan açık öğrenci sınıf constraint'i.
- `alumni.0006_alumniregistrationrequest_alumni_student_number_and_more`
  - Mezun kayıt talebi ve koşullu unique öğrenci numarası.
- `projects.0021_remove_projectcasestudy_github_url_and_more`
  - Repository path dönüşümü, GitHub cache/sync alanlarının kaldırılması, Team/Like/Feature/Update/Media değişiklikleri.
  - Geçersiz veya çakışan repository verisinde fail-fast.
- `core.0004_notification_dedupe_key_notification_title_and_more`
  - Bildirim başlığı, dedupe ve yeni türler.

Bu migration'ların tamamı uygulanmış (`[X]`) durumdadır.

## 5. Backup ve veri operasyonları

### 5.1 Oluşturulan yedekler

- `backups/pre-modernization-20260820-194034.sqlite3` — 1.998.848 byte  
  SHA-256: `9692A609AB69F3901CB860558A21199312A07B9CF6F84840B35078F096DF6C85`
- `backups/pre-modernization-source-20260820-194034.zip` — 1.151.035 byte  
  SHA-256: `21138595B30FDCBB8ECBCC5FB4688FBE1818CAF9A47A4F3A43E16594AD99EAC3`
- `backups/pre-class-constraint-20260820-202442.sqlite3` — 2.039.808 byte  
  SHA-256: `DE3CE78AE478F49A47A7011EA78CFB4B60933B411CFC98A57D42F397918D3793`
- `backups/pre-news-clear-20260820-202839-077776.sqlite3` — 2.056.192 byte  
  SHA-256: `8B63A283A42631B03AE1DC6F764BFA8B568DCBF2A1E94D81F62B614F2F5318F0`

### 5.2 Veri sayaçları

| Veri | Başlangıç | Son | Sonuç |
|---|---:|---:|---|
| Kullanıcı | 6 | 6 | Korundu |
| Akademisyen profili | 4 | 4 | Korundu |
| Mezun | 405 | 405 | Korundu |
| İş deneyimi | 1.128 | 1.128 | Korundu |
| Proje | 1 | 1 | Korundu |
| Teknoloji | 51 | 51 | Korundu |
| Kategori | 21 | 21 | Korundu |
| Haber (`Article`) | 63 | 0 | Plan gereği yedek sonrası silindi |
| Haber anahtar kelimesi | 0 | 0 | Dokunulmadı |

`clear_development_news --confirm` gerçek silinen Article sayısını **63** olarak raporladı. Akademisyen, mezun, iş deneyimi veya diğer iş tablolarından kayıt silinmedi.

### 5.3 Normalizasyon sonucu

- Normalize edilmiş Profile GitHub kullanıcı adı: **1**
- Normalize edilmiş Profile LinkedIn slug: **1**
- Düz metin PasswordReset kodu: **0**
- İçe aktarılmış Alumni sosyal bağlantıları: **405 kayıt üzerinde toplu dönüşüm yapılmadı**
- Mevcut veri içinde yeni alumni request/team/like/repository/website history kaydı: **0**; özellikler kullanıma hazırdır.
- “BST Yetkilisi” grubunda atanan permission: **14**

## 6. Test ve doğrulama sonuçları

Son tam komut:

```text
.\.venv\Scripts\python.exe manage.py test --verbosity 1
Found 155 test(s).
Ran 155 tests in 93.796s
OK
```

Dağılım sonucu: **155 passed / 0 failed / 0 skipped**.

Ayrıca:

```text
manage.py check                                  -> 0 sorun
manage.py makemigrations --check --dry-run       -> No changes detected
manage.py migrate --check                        -> exit 0 / bekleyen migration yok
manage.py showmigrations accounts alumni projects core -> tümü [X]
manage.py collectstatic --noinput --dry-run       -> 2 copied, 547 unmodified
python -m pip check                              -> No broken requirements found
```

Testlerde profil/sınıf/link doğrulama, website geçmişi, BST Yetkilisi sınırları, mezun bağlama/yeni/ret/unlink, repository path ve sync kaldırılması, görsel içerik/5 MB/tek kapak, like/feature, ekip daveti/idempotency, bildirim dedupe/tercih/IDOR, haber silme komutu, dashboard KPI'ları, e-posta hash/enumeration ve POST/permission kontrolleri kapsanıyor.

## 7. Görsel ve responsive QA

Giriş gerektirmeyen güncel sayfalar gerçek tarayıcıda 360, 768 ve 1440 px genişliklerde kontrol edildi:

- Ana sayfa
- Proje vitrini
- Ekip listesi
- İş birliği talebi formu
- Haberler
- KVKK metni

Kontrol edilen sayfalarda document-level yatay overflow bulunmadı. KVKK tablosu dar ekranda kendi kontrollü scroll alanında kalıyor. Form placeholder'ları, zorunlu seçimler ve koyu renk tasarım gözle doğrulandı.

Giriş yapılmış yönetim paneli için elde doğrulanmış kullanıcı parolası paylaşılmadığından gerçek oturumlu tarayıcı testi yapılmadı ve parola değiştirilmedi. Bu bölümün render/permission/endpoint davranışı otomatik testlerle doğrulandı; canlı kullanıcı kabul testi aşağıdaki manuel listede açıkça bırakıldı.

## 8. Manuel/harici işlemler

Aşağıdakiler kod eksikliği değildir; gerçek credential, domain veya kurum kararı gerektirdiği için tamamlandı sayılmamıştır:

1. **Gmail SMTP:** `.env` içine gerçek `EMAIL_HOST_USER`, Google Uygulama Şifresi olan `EMAIL_HOST_PASSWORD` ve `DEFAULT_FROM_EMAIL` girilmeli. Ardından:

   ```text
   .\.venv\Scripts\python.exe manage.py send_test_email --to gercek-alici@example.com
   ```

   Bu çalışma sırasında gerçek alıcı/credential olmadığı için dış e-posta gönderilmedi.

2. **Domain/DNS/HTTPS:** Canlı domain, DNS A/AAAA/CNAME, TLS sertifikası, `DJANGO_ALLOWED_HOSTS` ve `DJANGO_CSRF_TRUSTED_ORIGINS` sunucuda ayarlanmalı.

3. **Production depolama/yedek:** Kalıcı `SQLITE_DATABASE_PATH`, medya dizini, dosya izinleri, otomatik SQLite backup API işi ve dış depoya kopyalama kurulmalı. Trafik büyüdüğünde SQLite yazma kapasitesi izlenmeli; bu sürümde PostgreSQL'e geçiş yapılmadı.

4. **KVKK hukuki onayı:** Teknik KVKK sayfası mevcut; kurumun veri sorumlusu/iletişim/saklama süreleri hukuk birimince son kez onaylanmalı.

5. **Oturumlu manuel QA:** Admin, BST Yetkilisi, öğrenci, akademisyen ve mezun test hesaplarıyla dashboard, bildirim dropdown'u, moderasyon confirmation'ları ve alumni eşleştirme 360/768/1440 px'de kullanıcı kabul testinden geçirilmeli.

6. **İsteğe bağlı mevcut servisler:** Projede önceden bulunan Gemini/Sentry/Redis/S3 özellikleri kullanılacaksa kendi credential ve altyapıları ayrıca smoke test edilmelidir. GitHub API credential'ı artık yoktur ve gerekmemektedir.

## 9. Açık kalan durum

- Plan kapsamındaki model, migration, backend, template, permission ve otomatik test işleri uygulanmıştır.
- Gerçek Gmail gönderimi ve oturumlu manuel tarayıcı QA dış koşullar nedeniyle doğrulanmamıştır; bunlar bu raporda tamamlanmış gösterilmemiştir.
- Kaynak klasör Git repository olmadığı için commit/branch oluşturulmamıştır.
