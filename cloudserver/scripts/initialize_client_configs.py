#!/usr/bin/env python3
"""
Initialize Client Configurations from Existing Upload Data

This migration script:
1. Scans modem_checks table for unique (api_key, modem_id) pairs
2. Extracts configuration from most recent upload for each client
3. Creates ClientConfig entries with encryption
4. Sets initial mode to "one_time" (server provides once, client can modify)
5. Creates initial backup for rollback capability

Usage:
    python3 scripts/initialize_client_configs.py [--dry-run] [--mode MODE] [--force]

Options:
    --dry-run       Show what would be created without making changes
    --mode MODE     Set initial mode: "one_time" (default) or "locked"
    --force         Overwrite existing configs (use with caution!)
    --api-key KEY   Only process specific API key
    --modem-id ID   Only process specific modem ID
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, func, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.config_encryption import encrypt_config
from app.core.config_validation import validate_config
from app.models.client_config import ClientConfig, ConfigBackup, ConfigMode
from app.models import ModemCheck, APIKey


# Default configuration values extracted from uploaded data
DEFAULT_CONFIG_FIELDS = [
    'ModemAddress', 'IgnitePassword', 'SpeedTestEnabled', 'SpeedTestInterval',
    'PingCount', 'AutoUpdateEnabled', 'UpdateChannel', 'Silent', 'NoLogs',
    'LocalCleanupEnabled', 'LocalRetentionDays', 'EnableCloud', 'CloudHost',
    'CloudPort', 'CloudAPIKey', 'CloudPath', 'EnforceHTTPS', 'InsecureTLS'
]


def extract_config_from_upload(check_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract configuration from uploaded modem check data.

    Args:
        check_data: Full JSON data from modem check upload

    Returns:
        Dict containing extracted configuration fields
    """
    config = {}

    # Try to extract from client metadata if available
    if isinstance(check_data, dict):
        # Some fields might be at root level
        for field in DEFAULT_CONFIG_FIELDS:
            if field in check_data:
                config[field] = check_data[field]

    # Set sensible defaults for missing fields
    defaults = {
        'ModemAddress': 'autodetect',
        'IgnitePassword': '',
        'SpeedTestEnabled': True,
        'SpeedTestInterval': 1,
        'PingCount': 25,
        'AutoUpdateEnabled': True,
        'UpdateChannel': 'stable',
        'Silent': False,
        'NoLogs': False,
        'LocalCleanupEnabled': True,
        'LocalRetentionDays': 90,
        'EnableCloud': True,  # They're uploading, so cloud is enabled
        'CloudHost': '',
        'CloudPort': '22557',
        'CloudAPIKey': '',
        'CloudPath': '/',
        'EnforceHTTPS': True,
        'InsecureTLS': False
    }

    # Apply defaults for missing fields
    for field, default_value in defaults.items():
        if field not in config:
            config[field] = default_value

    return config


async def get_unique_clients(db: AsyncSession, api_key_filter: Optional[str] = None,
                             modem_id_filter: Optional[str] = None) -> list[Tuple[str, str]]:
    """
    Get unique (api_key, modem_id) pairs from modem_checks table.

    Args:
        db: Database session
        api_key_filter: Optional filter for specific API key
        modem_id_filter: Optional filter for specific modem ID

    Returns:
        List of (api_key, modem_id) tuples
    """
    # Build query
    query = select(distinct(ModemCheck.api_key), ModemCheck.modem_id)

    # Apply filters
    filters = []
    if api_key_filter:
        filters.append(ModemCheck.api_key == api_key_filter)
    if modem_id_filter:
        filters.append(ModemCheck.modem_id == modem_id_filter)

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    clients = [(row[0], row[1]) for row in result.all()]

    return clients


async def get_latest_check(db: AsyncSession, api_key: str, modem_id: str) -> Optional[ModemCheck]:
    """
    Get the most recent modem check for a client.

    Args:
        db: Database session
        api_key: Client API key
        modem_id: Client modem ID

    Returns:
        Most recent ModemCheck or None
    """
    query = select(ModemCheck).where(
        and_(
            ModemCheck.api_key == api_key,
            ModemCheck.modem_id == modem_id
        )
    ).order_by(ModemCheck.check_time.desc()).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def config_exists(db: AsyncSession, api_key: str, modem_id: str) -> bool:
    """
    Check if a ClientConfig already exists for this client.

    Args:
        db: Database session
        api_key: Client API key
        modem_id: Client modem ID

    Returns:
        True if config exists, False otherwise
    """
    query = select(ClientConfig).where(
        and_(
            ClientConfig.api_key == api_key,
            ClientConfig.modem_id == modem_id
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def create_client_config(db: AsyncSession, api_key: str, modem_id: str,
                               config_dict: Dict[str, Any], mode: str,
                               username: str = 'migration_script') -> ClientConfig:
    """
    Create a new ClientConfig entry with encryption and backup.

    Args:
        db: Database session
        api_key: Client API key
        modem_id: Client modem ID
        config_dict: Configuration dictionary
        mode: Config mode ("one_time" or "locked")
        username: Username for audit trail

    Returns:
        Created ClientConfig
    """
    # Validate configuration
    await validate_config(config_dict)

    # Encrypt configuration
    encrypted_blob, salt = await encrypt_config(config_dict)

    # Calculate config hash
    import json
    from app.core.config_sync import calculate_config_hash
    config_hash = calculate_config_hash(config_dict)

    # Create ClientConfig
    client_config = ClientConfig(
        api_key=api_key,
        modem_id=modem_id,
        config_plaintext=config_dict,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        mode=ConfigMode.LOCKED if mode == 'locked' else ConfigMode.ONE_TIME,
        version=1,
        encryption_salt=salt,
        created_by=username,
        updated_by=username,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    db.add(client_config)
    await db.flush()

    # Create initial backup
    backup = ConfigBackup(
        api_key=api_key,
        modem_id=modem_id,
        config_plaintext=config_dict,
        config_encrypted=encrypted_blob,
        config_hash=config_hash,
        mode=client_config.mode,
        version=1,
        encryption_salt=salt,
        backup_reason='initial_migration',
        backed_up_by=username,
        backup_timestamp=datetime.now(timezone.utc)
    )

    db.add(backup)

    return client_config


async def initialize_configs(dry_run: bool = False, mode: str = 'one_time',
                             force: bool = False, api_key_filter: Optional[str] = None,
                             modem_id_filter: Optional[str] = None):
    """
    Main migration function to initialize client configurations.

    Args:
        dry_run: If True, show what would be created without making changes
        mode: Initial mode for configs ("one_time" or "locked")
        force: If True, overwrite existing configs
        api_key_filter: Optional filter for specific API key
        modem_id_filter: Optional filter for specific modem ID
    """
    print("=" * 80)
    print("Client Configuration Initialization")
    print("=" * 80)
    print(f"Mode: {dry_run and 'DRY RUN' or 'LIVE'}")
    print(f"Default Mode: {mode}")
    print(f"Force Overwrite: {force}")
    if api_key_filter:
        print(f"API Key Filter: {api_key_filter}")
    if modem_id_filter:
        print(f"Modem ID Filter: {modem_id_filter}")
    print()

    async for db in get_async_session():
        try:
            # Get unique clients
            print("Scanning for unique clients...")
            clients = await get_unique_clients(db, api_key_filter, modem_id_filter)
            print(f"Found {len(clients)} unique client(s)")
            print()

            created_count = 0
            skipped_count = 0
            error_count = 0

            for api_key, modem_id in clients:
                try:
                    # Check if config already exists
                    exists = await config_exists(db, api_key, modem_id)

                    if exists and not force:
                        print(f"⏭  SKIP: {api_key[:12]}... / {modem_id} (already exists)")
                        skipped_count += 1
                        continue

                    # Get latest check to extract config
                    latest_check = await get_latest_check(db, api_key, modem_id)

                    if not latest_check:
                        print(f"⚠  WARN: {api_key[:12]}... / {modem_id} (no upload data found)")
                        skipped_count += 1
                        continue

                    # Extract configuration from upload data
                    config_dict = extract_config_from_upload(latest_check.full_data)

                    # Override cloud settings with actual values from database
                    config_dict['CloudAPIKey'] = api_key

                    # Print what we're creating
                    action = "OVERWRITE" if exists and force else "CREATE"
                    print(f"✓ {action}: {api_key[:12]}... / {modem_id}")
                    print(f"   Mode: {mode}")
                    print(f"   Config fields: {len(config_dict)}")

                    if not dry_run:
                        if exists and force:
                            # Delete existing config
                            await db.execute(
                                select(ClientConfig).where(
                                    and_(
                                        ClientConfig.api_key == api_key,
                                        ClientConfig.modem_id == modem_id
                                    )
                                ).delete()
                            )

                        # Create new config
                        await create_client_config(db, api_key, modem_id, config_dict, mode)
                        created_count += 1
                        print(f"   ✓ Created successfully")

                    print()

                except Exception as e:
                    print(f"✗ ERROR: {api_key[:12]}... / {modem_id}")
                    print(f"   {str(e)}")
                    print()
                    error_count += 1

            if not dry_run:
                await db.commit()
                print("=" * 80)
                print("Migration Complete!")
            else:
                print("=" * 80)
                print("Dry Run Complete (no changes made)")

            print(f"Created: {created_count}")
            print(f"Skipped: {skipped_count}")
            print(f"Errors: {error_count}")
            print("=" * 80)

        except Exception as e:
            await db.rollback()
            print(f"\n✗ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    """Parse arguments and run migration."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Initialize client configurations from existing upload data'
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be created without making changes')
    parser.add_argument('--mode', choices=['one_time', 'locked'], default='one_time',
                       help='Initial mode for configs (default: one_time)')
    parser.add_argument('--force', action='store_true',
                       help='Overwrite existing configs (use with caution!)')
    parser.add_argument('--api-key', type=str,
                       help='Only process specific API key')
    parser.add_argument('--modem-id', type=str,
                       help='Only process specific modem ID')

    args = parser.parse_args()

    # Run migration
    asyncio.run(initialize_configs(
        dry_run=args.dry_run,
        mode=args.mode,
        force=args.force,
        api_key_filter=args.api_key,
        modem_id_filter=args.modem_id
    ))


if __name__ == '__main__':
    main()
