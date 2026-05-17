# Eren API

Python **FastAPI** projesi — asenkron PostgreSQL bağlantısı, SQLAlchemy 2.0 ve asyncpg ile.

---

## 📁 Proje Yapısı

```
Eren/
├── app/
│   ├── __init__.py
│   ├── config.py       # pydantic-settings ile ortam değişkenleri
│   ├── database.py     # Async engine, session factory, Base, get_db()
│   ├── models.py       # Company & Report ORM modelleri
│   ├── schemas.py      # Pydantic request/response şemaları
│   ├── repository.py   # Async CRUD fonksiyonları
│   └── main.py         # FastAPI app, lifespan, tüm endpoint'ler
├── .env.example
└── requirements.txt
```

---

## ⚙️ Kurulum

### 1. Ortam değişkenlerini ayarla
```bash
cp .env.example .env
# .env dosyasını düzenle → DATABASE_URL'yi kendi PostgreSQL bilgileriyle güncelle
```

### 2. Sanal ortam oluştur ve bağımlılıkları kur
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. PostgreSQL veritabanını oluştur
```sql
CREATE DATABASE eren_db;
```

### 4. Uygulamayı başlat
```bash
uvicorn app.main:app --reload
```

Uygulama ilk çalıştığında `Base.metadata.create_all()` ile tabloları otomatik oluşturur.

---

## 🌐 API Endpoint'leri

| Method | URL | Açıklama |
|--------|-----|----------|
| `GET` | `/health` | Sistem ve DB sağlık kontrolü |
| `POST` | `/companies` | Yeni şirket oluştur |
| `GET` | `/companies` | Tüm şirketleri listele |
| `GET` | `/companies/{id}` | Tek şirket getir |
| `PATCH` | `/companies/{id}` | Şirketi kısmen güncelle |
| `DELETE` | `/companies/{id}` | Şirketi sil |
| `POST` | `/reports` | Yeni rapor oluştur |
| `GET` | `/reports` | Tüm raporları listele |
| `GET` | `/reports/{id}` | Tek rapor getir |
| `GET` | `/companies/{id}/reports` | Şirkete ait raporlar |
| `PATCH` | `/reports/{id}` | Raporu kısmen güncelle |
| `DELETE` | `/reports/{id}` | Raporu sil |

**Swagger UI**: http://localhost:8000/docs  
**ReDoc**: http://localhost:8000/redoc

---

## 🔍 Health Check Örneği

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "database": "ok",
  "app_name": "Eren API",
  "app_version": "1.0.0",
  "detail": null
}
```

---

## 🗄️ Veritabanı Modelleri

### Company
| Alan | Tip | Açıklama |
|------|-----|----------|
| `id` | int (PK) | Otomatik artan |
| `name` | varchar(255) | Şirket adı |
| `tax_number` | varchar(50) | Vergi no (unique) |
| `created_at` | timestamptz | UTC oluşturulma zamanı |

### Report
| Alan | Tip | Açıklama |
|------|-----|----------|
| `id` | int (PK) | Otomatik artan |
| `company_id` | int (FK) | companies.id'ye referans |
| `trust_score` | numeric(5,2) | 0–100 arası güven skoru |
| `risk_summary` | text | Risk özeti |
| `market_data` | text | Piyasa verisi (JSON vb.) |
| `created_at` | timestamptz | UTC oluşturulma zamanı |

---

## 📝 Notlar

- **Transaction yönetimi** `get_db()` bağımlılığında merkezi olarak yapılır; repository fonksiyonları yalnızca `flush()` çağırır.
- **Üretim ortamında** tablo yönetimi için `Base.metadata.create_all` yerine **Alembic** kullanın.
- `Company` silindiğinde ilişkili `Report`'lar `CASCADE` ile otomatik silinir.
