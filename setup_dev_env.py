import os
import glob
import asyncio
import subprocess
import logging
import sys
import logging

logging.basicConfig(level=logging.INFO)

async def clean_db():
    if os.path.exists("test.db"):
        os.remove("test.db")
        logging.info("Deleted test.db")
    
    # Clean migrations/versions directory
    for f in glob.glob("migrations/versions/*.py"):
        if "__init__.py" not in f:
            os.remove(f)
            logging.info(f"Deleted migration: {f}")
    
    # Clear alembic_version table in the database
    from app.database import engine
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            logging.info("Dropped alembic_version table")
    except Exception as e:
        logging.warning(f"Could not drop alembic_version: {e}")

async def create_test_user():
    from app.database import AsyncSessionLocal
    from app.models import User
    from app.auth import get_password_hash

    async with AsyncSessionLocal() as session:
        # Check if user exists
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.email == "test@test.com"))
        user = result.scalar_one_or_none()
        if not user:
            new_user = User(
                email="test@test.com",
                hashed_password=get_password_hash("password123"),
                full_name="Test User",
                company_name="Test Company",
                role="user"
            )
            session.add(new_user)
            await session.commit()
            logging.info("Test user created (test@test.com / password123)")
        else:
            logging.info("Test user already exists.")

async def async_main():
    await clean_db()
    
    # Create tables using reset_db.py or alembic
    logging.info("Running alembic revision --autogenerate -m 'Initial migration'")
    subprocess.run([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "Initial migration"], check=True)
    
    logging.info("Running alembic upgrade head")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

    await create_test_user()
    
    logging.info("Dev environment setup complete.")

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
