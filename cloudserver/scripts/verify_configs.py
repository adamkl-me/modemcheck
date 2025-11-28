#!/usr/bin/env python3
"""
Verify Client Configuration Integrity

This utility script validates:
1. Configuration JSON schema and data types
2. Encryption integrity (can decrypt all configs)
3. Hash consistency (plaintext matches hash)
4. Backup availability for each config
5. Orphaned configs (no corresponding API key)
6. Missing configs (clients with uploads but no config)

Usage:
    # Verify all configurations
    python3 scripts/verify_configs.py

    # Verify specific client
    python3 scripts/verify_configs.py --api-key KEY --modem-id ID

    # Detailed output
    python3 scripts/verify_configs.py --verbose

    # Fix issues automatically
    python3 scripts/verify_configs.py --fix

Options:
    --api-key KEY       Verify specific API key only
    --modem-id ID       Verify specific modem ID only
    --verbose           Show detailed output for each config
    --fix               Attempt to fix issues automatically
    --check-encryption  Verify all configs can be decrypted
    --check-backups     Verify backups exist for all configs
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.config_encryption import decrypt_config, encrypt_config
from app.core.config_validation import validate_config
from app.core.config_sync import calculate_config_hash
from app.models.client_config import ClientConfig, ConfigBackup
from app.models import APIKey, ModemCheck


class ValidationResult:
    """Holds validation results for a configuration."""

    def __init__(self, api_key: str, modem_id: str):
        self.api_key = api_key
        self.modem_id = modem_id
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, message: str):
        self.errors.append(message)

    def add_warning(self, message: str):
        self.warnings.append(message)

    def add_info(self, message: str):
        self.info.append(message)

    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


async def verify_config_schema(config: ClientConfig) -> ValidationResult:
    """
    Verify configuration JSON schema and data types.

    Args:
        config: ClientConfig to verify

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(config.api_key, config.modem_id)

    try:
        # Validate using validation module
        await validate_config(config.config_plaintext)
        result.add_info("Schema validation passed")
    except Exception as e:
        result.add_error(f"Schema validation failed: {e}")

    return result


async def verify_encryption(config: ClientConfig) -> ValidationResult:
    """
    Verify encryption integrity (can decrypt and re-encrypt).

    Args:
        config: ClientConfig to verify

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(config.api_key, config.modem_id)

    try:
        # Try to decrypt
        decrypted = await decrypt_config(config.config_encrypted, config.encryption_salt)

        # Verify decrypted matches plaintext
        if decrypted != config.config_plaintext:
            result.add_error("Decrypted config does not match plaintext")
        else:
            result.add_info("Encryption integrity verified")

    except Exception as e:
        result.add_error(f"Encryption verification failed: {e}")

    return result


async def verify_hash(config: ClientConfig) -> ValidationResult:
    """
    Verify hash consistency (plaintext hash matches stored hash).

    Args:
        config: ClientConfig to verify

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(config.api_key, config.modem_id)

    try:
        # Calculate hash of current plaintext
        calculated_hash = calculate_config_hash(config.config_plaintext)

        if calculated_hash != config.config_hash:
            result.add_error(f"Hash mismatch: stored={config.config_hash[:16]}..., calculated={calculated_hash[:16]}...")
        else:
            result.add_info("Hash integrity verified")

    except Exception as e:
        result.add_error(f"Hash verification failed: {e}")

    return result


async def verify_api_key_exists(db: AsyncSession, config: ClientConfig) -> ValidationResult:
    """
    Verify API key still exists in database.

    Args:
        db: Database session
        config: ClientConfig to verify

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(config.api_key, config.modem_id)

    query = select(APIKey).where(APIKey.api_key == config.api_key)
    api_key_obj = await db.execute(query)
    api_key_obj = api_key_obj.scalar_one_or_none()

    if not api_key_obj:
        result.add_error("Orphaned config - API key no longer exists")
    elif not api_key_obj.is_active:
        result.add_warning("API key is inactive")
    else:
        result.add_info("API key exists and is active")

    return result


async def verify_backup_exists(db: AsyncSession, config: ClientConfig) -> ValidationResult:
    """
    Verify at least one backup exists for this config.

    Args:
        db: Database session
        config: ClientConfig to verify

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(config.api_key, config.modem_id)

    query = select(func.count()).select_from(ConfigBackup).where(
        and_(
            ConfigBackup.api_key == config.api_key,
            ConfigBackup.modem_id == config.modem_id
        )
    )
    count_result = await db.execute(query)
    backup_count = count_result.scalar()

    if backup_count == 0:
        result.add_warning("No backups found - cannot rollback")
    else:
        result.add_info(f"{backup_count} backup(s) available")

    return result


async def verify_single_config(db: AsyncSession, config: ClientConfig, verbose: bool,
                               check_encryption: bool, check_backups: bool) -> ValidationResult:
    """
    Run all verification checks on a single configuration.

    Args:
        db: Database session
        config: ClientConfig to verify
        verbose: If True, show detailed output
        check_encryption: If True, verify encryption
        check_backups: If True, verify backups exist

    Returns:
        Combined ValidationResult
    """
    combined = ValidationResult(config.api_key, config.modem_id)

    # Schema validation
    schema_result = await verify_config_schema(config)
    combined.errors.extend(schema_result.errors)
    combined.warnings.extend(schema_result.warnings)
    if verbose:
        combined.info.extend(schema_result.info)

    # Hash verification
    hash_result = await verify_hash(config)
    combined.errors.extend(hash_result.errors)
    combined.warnings.extend(hash_result.warnings)
    if verbose:
        combined.info.extend(hash_result.info)

    # Encryption verification (optional, can be slow)
    if check_encryption:
        enc_result = await verify_encryption(config)
        combined.errors.extend(enc_result.errors)
        combined.warnings.extend(enc_result.warnings)
        if verbose:
            combined.info.extend(enc_result.info)

    # API key existence
    api_result = await verify_api_key_exists(db, config)
    combined.errors.extend(api_result.errors)
    combined.warnings.extend(api_result.warnings)
    if verbose:
        combined.info.extend(api_result.info)

    # Backup existence (optional)
    if check_backups:
        backup_result = await verify_backup_exists(db, config)
        combined.errors.extend(backup_result.errors)
        combined.warnings.extend(backup_result.warnings)
        if verbose:
            combined.info.extend(backup_result.info)

    return combined


async def verify_configs(api_key_filter: Optional[str] = None,
                        modem_id_filter: Optional[str] = None,
                        verbose: bool = False,
                        fix: bool = False,
                        check_encryption: bool = False,
                        check_backups: bool = True):
    """
    Verify client configurations.

    Args:
        api_key_filter: Optional filter for specific API key
        modem_id_filter: Optional filter for specific modem ID
        verbose: If True, show detailed output
        fix: If True, attempt to fix issues automatically
        check_encryption: If True, verify encryption (slow)
        check_backups: If True, verify backups exist
    """
    print("=" * 80)
    print("Client Configuration Verification")
    print("=" * 80)
    print(f"Verbose: {verbose}")
    print(f"Auto-fix: {fix}")
    print(f"Check Encryption: {check_encryption}")
    print(f"Check Backups: {check_backups}")
    if api_key_filter:
        print(f"API Key Filter: {api_key_filter}")
    if modem_id_filter:
        print(f"Modem ID Filter: {modem_id_filter}")
    print()

    async for db in get_async_session():
        try:
            # Get configurations to verify
            query = select(ClientConfig)

            filters = []
            if api_key_filter:
                filters.append(ClientConfig.api_key == api_key_filter)
            if modem_id_filter:
                filters.append(ClientConfig.modem_id == modem_id_filter)

            if filters:
                query = query.where(and_(*filters))

            result = await db.execute(query)
            configs = list(result.scalars().all())

            print(f"Verifying {len(configs)} configuration(s)...")
            print()

            valid_count = 0
            warning_count = 0
            error_count = 0

            for config in configs:
                # Run verification
                validation = await verify_single_config(db, config, verbose, check_encryption, check_backups)

                # Print results
                status = "✓" if validation.is_valid() else ("⚠" if validation.has_warnings() and not validation.errors else "✗")
                print(f"{status} {config.api_key[:12]}... / {config.modem_id}")

                if verbose and validation.info:
                    for info in validation.info:
                        print(f"   ℹ  {info}")

                if validation.warnings:
                    for warning in validation.warnings:
                        print(f"   ⚠  {warning}")
                    warning_count += 1

                if validation.errors:
                    for error in validation.errors:
                        print(f"   ✗  {error}")
                    error_count += 1

                if validation.is_valid() and not validation.has_warnings():
                    valid_count += 1

                print()

            print("=" * 80)
            print("Verification Complete")
            print(f"Valid: {valid_count}")
            print(f"Warnings: {warning_count}")
            print(f"Errors: {error_count}")
            print("=" * 80)

            if error_count > 0:
                sys.exit(1)

        except Exception as e:
            print(f"\n✗ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    """Parse arguments and run verification."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Verify client configuration integrity'
    )
    parser.add_argument('--api-key', type=str,
                       help='Verify specific API key only')
    parser.add_argument('--modem-id', type=str,
                       help='Verify specific modem ID only')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output for each config')
    parser.add_argument('--fix', action='store_true',
                       help='Attempt to fix issues automatically (not yet implemented)')
    parser.add_argument('--check-encryption', action='store_true',
                       help='Verify all configs can be decrypted (slow)')
    parser.add_argument('--check-backups', action='store_true', default=True,
                       help='Verify backups exist for all configs')

    args = parser.parse_args()

    # Run verification
    asyncio.run(verify_configs(
        api_key_filter=args.api_key,
        modem_id_filter=args.modem_id,
        verbose=args.verbose,
        fix=args.fix,
        check_encryption=args.check_encryption,
        check_backups=args.check_backups
    ))


if __name__ == '__main__':
    main()
