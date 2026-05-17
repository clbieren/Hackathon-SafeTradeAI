"""
reset_db.py
===========
Alembic olmadan veritabanı şemasını sıfırlayıp yeniden oluşturur.
Tüm mevcut tablolar DROP edilir, ardından models.py'deki güncel
şemaya göre yeniden CREATE edilir.

KULLANIM (Eren/ dizininden):
    python reset_db.py               → Onay sorar
    python reset_db.py --yes         → Onaysız çalışır (CI/Docker için)

⚠️  Bu script tüm verileri SİLER. Sadece geliştirme ortamında kullan.
"""

import argparse
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("reset_db")


async def reset() -> None:
    # İmport'ları burada yapıyoruz — env yüklenmiş olsun diye
    from app.database import engine, Base  # noqa: PLC0415
    import app.models  # noqa: F401 — modelleri Base.metadata'ya kayıt etmek için

    logger.info("Mevcut tablolar DROP ediliyor...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("DROP tamamlandı.")

    logger.info("Tablolar yeni şemaya göre CREATE ediliyor...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("CREATE tamamlandı.")

    # Hangi tabloların oluşturulduğunu logla
    table_names = list(Base.metadata.tables.keys())
    logger.info("Oluşturulan tablolar: %s", table_names)

    await engine.dispose()
    logger.info("✅ Veritabanı şeması başarıyla güncellendi.")


def main() -> None:
    parser = argparse.ArgumentParser(description="SafeTrade AI — DB Şema Sıfırlayıcı")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Onay sormadan çalıştır (CI ortamları için)",
    )
    args = parser.parse_args()

    if not args.yes:
        print("\n⚠️  DİKKAT: Bu işlem TÜM verileri silip şemayı yeniden oluşturacak!")
        confirm = input("Devam etmek için 'evet' yazın: ").strip().lower()
        if confirm not in ("evet", "yes", "e", "y"):
            print("İptal edildi.")
            sys.exit(0)

    asyncio.run(reset())


if __name__ == "__main__":
    main()
