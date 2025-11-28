#!/usr/bin/env python3
"""
Bulk Lock/Unlock Client Configurations

This utility script allows administrators to:
1. Lock configurations to prevent client-side modifications
2. Unlock configurations to allow client modifications
3. Bulk operations on all configs or filtered subset
4. Create backups before mode changes

Usage:
    # Lock all configurations
    python3 scripts/lock_configs.py --lock --all

    # Unlock specific client
    python3 scripts/lock_configs.py --unlock --api-key KEY --modem-id ID

    # Lock all configs for a specific API key
    python3 scripts/lock_configs.py --lock --api-key KEY

    # Dry run to see what would change
    python3 scripts/lock_configs.py --lock --all --dry-run

Options:
    --lock              Lock configurations (server enforces, client cannot modify)
    --unlock            Unlock configurations (one-time mode, client can modify)
    --all               Apply to all configurations
    --api-key KEY       Filter by API key
    --modem-id ID       Filter by modem ID
    --dry-run           Show what would change without making changes
    --username USER     Username for audit trail (default: admin_script)
    --reason REASON     Reason for mode change (logged in audit)
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.client_config import ClientConfig, ConfigBackup, ConfigAuditLog, ConfigMode


async def get_configs_to_update(db: AsyncSession, api_key_filter: Optional[str] = None,
                                modem_id_filter: Optional[str] = None,
                                all_configs: bool = False) -> List[ClientConfig]:
    """
    Get configurations to update based on filters.

    Args:
        db: Database session
        api_key_filter: Optional filter for specific API key
        modem_id_filter: Optional filter for specific modem ID
        all_configs: If True, get all configurations

    Returns:
        List of ClientConfig objects
    """
    query = select(ClientConfig)

    # Apply filters
    filters = []
    if api_key_filter:
        filters.append(ClientConfig.api_key == api_key_filter)
    if modem_id_filter:
        filters.append(ClientConfig.modem_id == modem_id_filter)

    if filters:
        query = query.where(and_(*filters))
    elif not all_configs:
        # Safety check: require explicit --all flag
        raise ValueError("Must specify --all, --api-key, or --modem-id")

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_backup_before_mode_change(db: AsyncSession, config: ClientConfig,
                                           username: str, reason: str):
    """
    Create backup before changing mode.

    Args:
        db: Database session
        config: ClientConfig to backup
        username: Username for audit trail
        reason: Reason for backup
    """
    backup = ConfigBackup(
        api_key=config.api_key,
        modem_id=config.modem_id,
        config_plaintext=config.config_plaintext,
        config_encrypted=config.config_encrypted,
        config_hash=config.config_hash,
        mode=config.mode,
        version=config.version,
        encryption_salt=config.encryption_salt,
        backup_reason=reason,
        backed_up_by=username,
        backup_timestamp=datetime.now(timezone.utc)
    )
    db.add(backup)


async def create_audit_log(db: AsyncSession, config: ClientConfig, old_mode: str,
                          new_mode: str, username: str, reason: str, ip_address: str = '127.0.0.1'):
    """
    Create audit log entry for mode change.

    Args:
        db: Database session
        config: ClientConfig that was modified
        old_mode: Previous mode
        new_mode: New mode
        username: Username for audit trail
        reason: Reason for change
        ip_address: IP address of requester
    """
    import hashlib

    # Hash API key for privacy
    api_key_hash = hashlib.sha256(config.api_key.encode()).hexdigest()

    audit_log = ConfigAuditLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        api_key_hash=api_key_hash,
        ip_address=ip_address,
        api_key=config.api_key,
        modem_id=config.modem_id,
        action='mode_change',
        config_summary={'reason': reason},
        old_version=config.version,
        new_version=config.version,  # Version unchanged
        old_mode=ConfigMode.LOCKED if old_mode == 'locked' else ConfigMode.ONE_TIME,
        new_mode=ConfigMode.LOCKED if new_mode == 'locked' else ConfigMode.ONE_TIME,
        success=True,
        failure_reason=None
    )
    db.add(audit_log)


async def lock_unlock_configs(lock: bool, dry_run: bool = False, all_configs: bool = False,
                              api_key_filter: Optional[str] = None,
                              modem_id_filter: Optional[str] = None,
                              username: str = 'admin_script',
                              reason: str = 'bulk_mode_change'):
    """
    Lock or unlock client configurations.

    Args:
        lock: If True, lock configs; if False, unlock configs
        dry_run: If True, show what would change without making changes
        all_configs: If True, apply to all configurations
        api_key_filter: Optional filter for specific API key
        modem_id_filter: Optional filter for specific modem ID
        username: Username for audit trail
        reason: Reason for mode change
    """
    action = "LOCK" if lock else "UNLOCK"
    new_mode = "locked" if lock else "one_time"

    print("=" * 80)
    print(f"Bulk Configuration {action}")
    print("=" * 80)
    print(f"Mode: {dry_run and 'DRY RUN' or 'LIVE'}")
    print(f"New Mode: {new_mode}")
    print(f"Username: {username}")
    print(f"Reason: {reason}")
    if api_key_filter:
        print(f"API Key Filter: {api_key_filter}")
    if modem_id_filter:
        print(f"Modem ID Filter: {modem_id_filter}")
    if all_configs:
        print(f"Scope: ALL CONFIGURATIONS")
    print()

    async for db in get_async_session():
        try:
            # Get configurations to update
            print("Fetching configurations...")
            configs = await get_configs_to_update(db, api_key_filter, modem_id_filter, all_configs)
            print(f"Found {len(configs)} configuration(s)")
            print()

            if len(configs) == 0:
                print("No configurations found matching criteria.")
                return

            # Confirm if not dry run and many configs
            if not dry_run and all_configs and len(configs) > 10:
                print(f"⚠️  WARNING: About to change mode for {len(configs)} configurations!")
                confirm = input(f"Type 'yes' to confirm: ")
                if confirm.lower() != 'yes':
                    print("Aborted.")
                    return
                print()

            changed_count = 0
            skipped_count = 0

            for config in configs:
                old_mode = config.mode.value
                new_mode_enum = ConfigMode.LOCKED if lock else ConfigMode.ONE_TIME

                # Skip if already in target mode
                if config.mode == new_mode_enum:
                    print(f"⏭  SKIP: {config.api_key[:12]}... / {config.modem_id} (already {new_mode})")
                    skipped_count += 1
                    continue

                # Print what we're changing
                print(f"✓ CHANGE: {config.api_key[:12]}... / {config.modem_id}")
                print(f"   Old Mode: {old_mode}")
                print(f"   New Mode: {new_mode}")
                print(f"   Version: {config.version}")

                if not dry_run:
                    # Create backup before change
                    await create_backup_before_mode_change(db, config, username, f"mode_change_{reason}")

                    # Create audit log
                    await create_audit_log(db, config, old_mode, new_mode, username, reason)

                    # Update mode
                    config.mode = new_mode_enum
                    config.updated_by = username
                    config.updated_at = datetime.now(timezone.utc)

                    db.add(config)
                    changed_count += 1
                    print(f"   ✓ Updated successfully")

                print()

            if not dry_run:
                await db.commit()
                print("=" * 80)
                print("Operation Complete!")
            else:
                print("=" * 80)
                print("Dry Run Complete (no changes made)")

            print(f"Changed: {changed_count}")
            print(f"Skipped: {skipped_count}")
            print(f"Total: {len(configs)}")
            print("=" * 80)

        except Exception as e:
            await db.rollback()
            print(f"\n✗ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    """Parse arguments and run script."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Bulk lock/unlock client configurations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Lock all configurations (with confirmation)
  python3 scripts/lock_configs.py --lock --all

  # Unlock specific client
  python3 scripts/lock_configs.py --unlock --api-key abc123 --modem-id ARRIS-AABBCC

  # Lock all configs for specific API key (dry run)
  python3 scripts/lock_configs.py --lock --api-key abc123 --dry-run

  # Unlock all with custom reason
  python3 scripts/lock_configs.py --unlock --all --reason "Allow client customization"
        """
    )

    # Action (required)
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument('--lock', action='store_true',
                             help='Lock configurations (server enforces)')
    action_group.add_argument('--unlock', action='store_true',
                             help='Unlock configurations (one-time mode)')

    # Scope (one required)
    scope_group = parser.add_argument_group('scope', 'Specify which configs to update')
    scope_group.add_argument('--all', action='store_true',
                            help='Apply to all configurations')
    scope_group.add_argument('--api-key', type=str,
                            help='Filter by API key')
    scope_group.add_argument('--modem-id', type=str,
                            help='Filter by modem ID')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would change without making changes')
    parser.add_argument('--username', type=str, default='admin_script',
                       help='Username for audit trail (default: admin_script)')
    parser.add_argument('--reason', type=str, default='bulk_mode_change',
                       help='Reason for mode change (default: bulk_mode_change)')

    args = parser.parse_args()

    # Validate scope
    if not args.all and not args.api_key and not args.modem_id:
        parser.error("Must specify --all, --api-key, or --modem-id")

    # Run operation
    asyncio.run(lock_unlock_configs(
        lock=args.lock,
        dry_run=args.dry_run,
        all_configs=args.all,
        api_key_filter=args.api_key,
        modem_id_filter=args.modem_id,
        username=args.username,
        reason=args.reason
    ))


if __name__ == '__main__':
    main()
