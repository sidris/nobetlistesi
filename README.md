# Nöbet Çizelgesi — Streamlit + Supabase

Ortak (çok kullanıcılı) nöbet çizelgesi. Yönetici şifreyle düzenler, herkes
aynı canlı çizelgeyi görür. Veri Supabase'te (tek JSONB satırı) tutulur.

## 1) Supabase (bir kere)
1. Supabase panelinde **SQL Editor** → `supabase_setup.sql` içeriğini yapıştırıp **Run**.
2. **Project Settings → API**'den şunları al:
   - **Project URL** → `SUPABASE_URL`
   - **anon public** anahtarı → `SUPABASE_KEY` (basit kurulum; verdiğim RLS
     politikaları buna izin verir). Daha sıkı istersen `service_role` anahtarını
     kullan (yalnızca sunucu tarafında, secrets içinde durur).

## 2) Şifre ve anahtarlar
`.streamlit/secrets.toml.example` dosyasını `.streamlit/secrets.toml` yapıp doldur:
```
SUPABASE_URL = "https://XXXX.supabase.co"
SUPABASE_KEY = "eyJ..."
ADMIN_PASSWORD = "güçlü-şifre"
```

## 3) Çalıştırma
**Yerel:**
```
pip install -r requirements.txt
streamlit run app.py
```
**Streamlit Community Cloud (ücretsiz, ortak erişim):**
1. Bu klasörü bir GitHub deposuna koy.
2. share.streamlit.io → New app → depo/branch/`app.py` seç.
3. **Settings → Secrets** kısmına yukarıdaki üç değeri yapıştır → Deploy.
   Uygulama URL'ini ekibinle paylaş.

## Kullanım
- Sağ üstten **Düzenle** (şifre) ile düzenleme açılır; diğerleri sadece görür.
- **Kişiler & Görevler / Kurallar / İzinler & Notlar / Ayarlar** sekmelerinden
  düzenle, sonra **Ayarlar → Oluştur & Kaydet** ile çizelgeyi üret.
- **Elle Atama** sekmesi: bir işi kişiden kişiye taşı (cerrahi; kaynağında üstü
  çizili iz kalır, sayılar güncellenir, başka hücre değişmez).
- **Çizelge** sekmesi: tablo + "herkes her işi kaç kez yaptı" matrisi + Excel.

## Mantık (özet)
- X Takibi sabit sırayla çıpa (Özlem→…→Mine→Özlem), izinli atlanır.
- Kanallar her hafta 1 kişi, sırayla döndürülerek herkese eşit.
- Round-robin: herkes bir işi yapmadan sıra başa dönmez; aynı iş üst üste gelmez.
- İzin: sadece izinlinin işleri boş/CNN-NTV-A Para izleyenlere aktarılır; hafta
  geneli değişmez. Ağırlık yalnızca gösterim içindir.
