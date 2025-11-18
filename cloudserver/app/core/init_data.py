"""
Initialize default data for the application.

Creates default admin user if database is empty.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.user import UserRole
from app.core.security import hash_password


async def create_default_admin():
    """
    Create default admin user if no users exist.

    Default credentials:
    - Username: admin
    - Password: AdminPass123! (for test environment)
    - Password: changeme (for production - documented, must be changed on first login)
    - Role: admin
    - must_change_password: True (forces password change on first login in production)
    """
    # Import here to avoid circular dependency and ensure init_db() has run
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            # Check if any users exist
            result = await session.execute(select(User))
            existing_users = result.scalars().first()

            if existing_users is not None:
                # Users already exist, don't create default admin
                return

            # Determine password based on environment
            from app.core.config import settings
            if settings.is_test():
                password = "AdminPass123!"  # Test password matches test fixtures
                must_change = False  # Don't force change in tests
            else:
                password = "changeme"  # Production default
                must_change = True  # Force change on first login

            # Create default admin user
            admin_user = User(
                username="admin",
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                created_at=datetime.utcnow(),
                must_change_password=must_change
            )

            session.add(admin_user)
            await session.commit()

            env_label = "test" if settings.is_test() else "production"
            print(f"✓ Created default admin user for {env_label} environment")
            if not settings.is_test():
                print("  Username: admin")
                print("  Password: changeme")
                print("  ⚠️  Please change this password on first login!")

        except Exception as e:
            await session.rollback()
            # Ignore duplicate key errors (happens when multiple workers start simultaneously)
            if "duplicate key" in str(e).lower() or "already exists" in str(e).lower():
                # Another worker already created the admin user
                return
            # For other errors, print and re-raise
            print(f"Error creating default admin user: {e}")
            raise
