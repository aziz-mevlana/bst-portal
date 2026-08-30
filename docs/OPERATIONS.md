# BST Portal operasyon rehberi

## Ortamlar

Bu sürüm geliştirme ve canlı ortamda bilinçli olarak SQLite kullanır. Veritabanı yolu `SQLITE_DATABASE_PATH` ile değiştirilebilir; göreli yollar proje köküne göre çözülür. Gerçek gizli bilgiler yalnızca sunucu ortam değişkenlerinde saklanmalıdır.

SQLite örneği:

```text
SQLITE_DATABASE_PATH=db.sqlite3
SQLITE_TIMEOUT_SECONDS=20
```

S3 uyumlu depolama `USE_S3=True` ile açılır. Bucket CORS ve içerik türü kuralları, güvenilmeyen medyayı ana uygulama origin'inden ayrı sunacak şekilde yapılandırılmalıdır.

## Yedekleme

- SQLite: yazma trafiği durdurulduktan sonra SQLite backup API ile tutarlı kopya; dosyayı çalışan süreç sırasında sıradan dosya kopyasıyla çoğaltmayın.
- Medya: bucket versioning ve ayrı hedefe günlük replikasyon.
- Saklama: günlük 14, haftalık 8, aylık 12 kopya önerilir.
- Her ay izole ortamda geri yükleme tatbikatı yapılmalıdır.

## Geri yükleme kontrol listesi

1. Olay zamanını ve kullanılacak doğrulanmış yedeği belirleyin.
2. Yazma trafiğini durdurun.
3. Mevcut dosyayı ayrıca saklayıp doğrulanmış SQLite yedeğini yeni bir dosya adıyla geri yükleyin.
4. Migration durumunu, kayıt sayılarını ve foreign key bütünlüğünü kontrol edin.
5. Medya yedeğini ayrı prefix altında geri yükleyip örnek dosyaları doğrulayın.
6. `/health/`, giriş, proje, mezun ve admin akışlarını test edin.
7. Doğrulama tamamlandıktan sonra uygulamayı geri yüklenen `SQLITE_DATABASE_PATH` ile başlatın.

Kod deposundaki dosyalar tek başına gerçek bir yedek değildir.
