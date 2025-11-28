"""
Configuration validation for client configurations.

Provides multi-layer validation:
1. JSON schema validation (structure and types)
2. Security validation (XSS, SQL injection, path traversal)
3. Value range validation (bounds checking)
4. Optional URL reachability testing

Used by both sync endpoint (validating client configs) and
admin endpoint (validating server-pushed configs).
"""

import logging
import re
import asyncio
from typing import Dict, Any, List, Tuple
from urllib.parse import urlparse

from app.core.errors import ConfigValidationError

logger = logging.getLogger(__name__)


# JSON Schema for client configuration
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "ModemAddress": {"type": "string"},
        "IgnitePassword": {"type": "string"},
        "SpeedTestEnabled": {"type": "boolean"},
        "SpeedTestInterval": {"type": "integer"},
        "SpeedTestConnections": {"type": "integer"},
        "PingCount": {"type": "integer"},
        "AutoUpdateEnabled": {"type": "boolean"},
        "UpdateChannel": {"type": "string"},
        "Silent": {"type": "boolean"},
        "NoLogs": {"type": "boolean"},
        "LocalCleanupEnabled": {"type": "boolean"},
        "LocalRetentionDays": {"type": "integer"},
        "EnableCloud": {"type": "boolean"},
        "CloudHost": {"type": "string"},
        "CloudPort": {"type": "string"},
        "CloudAPIKey": {"type": "string"},
        "CloudPath": {"type": "string"},
        "EnforceHTTPS": {"type": "boolean"},
        "InsecureTLS": {"type": "boolean"},
    },
    "additionalProperties": True,  # Allow extra fields for forward compatibility
}


# Value constraints
VALUE_CONSTRAINTS = {
    "SpeedTestInterval": {"min": 1, "max": 1000},
    "SpeedTestConnections": {"min": 1, "max": 16},  # Parallel connections for speed tests
    "PingCount": {"min": 1, "max": 100},
    "LocalRetentionDays": {"min": 1, "max": 3650},  # 1 day to 10 years
    "UpdateChannel": {"enum": ["stable", "beta", "test"]},
}


# Security patterns (potential injection attacks)
# NOTE: These configs are stored as JSONB and never used in SQL queries or shell commands.
# This validation is defense-in-depth with more specific patterns to reduce false positives.
SECURITY_PATTERNS = {
    "sql_injection": [
        # More specific: SQL keywords followed by typical SQL syntax
        r"(\bSELECT\s+.+\s+FROM\b)",
        r"(\bINSERT\s+INTO\b)",
        r"(\bUPDATE\s+.+\s+SET\b)",
        r"(\bDELETE\s+FROM\b)",
        r"(\bDROP\s+(TABLE|DATABASE|INDEX)\b)",
        r"(\bUNION\s+(ALL\s+)?SELECT\b)",
        # SQL comments that indicate injection
        r"';\s*--",
        r"'\s*OR\s+'",
        r"'\s*OR\s+1\s*=\s*1",
    ],
    "xss": [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"onerror\s*=",
        r"onload\s*=",
        r"<iframe",
    ],
    "path_traversal": [
        # More specific: path traversal sequences that access parent directories
        r"/\.\./",  # Unix-style
        r"\\\.\.\\",  # Windows-style
        r"%2e%2e[/%]",  # URL encoded
        r"\.\.(/|\\){2,}",  # Multiple traversals
    ],
    "command_injection": [
        # More specific: dangerous command patterns
        r";\s*(rm|del|format|mkfs|wget|curl)\s",
        r"\$\([^)]+\)",  # Command substitution
        r"`[^`]+`",  # Backtick command substitution
    ],
}


def validate_schema(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration against JSON schema.

    Args:
        config: Configuration dictionary to validate

    Returns:
        List of validation errors (empty if valid)

    Example:
        >>> errors = validate_schema({"SpeedTestEnabled": "not a bool"})
        >>> errors
        ['Field SpeedTestEnabled: expected boolean, got string']
    """
    errors = []

    # Check field types
    for field, expected_type_info in CONFIG_SCHEMA["properties"].items():
        if field not in config:
            continue  # Optional fields

        value = config[field]
        expected_type = expected_type_info["type"]

        # Type checking
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field {field}: expected string, got {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field {field}: expected boolean, got {type(value).__name__}")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"Field {field}: expected integer, got {type(value).__name__}")

    return errors


def validate_values(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration values against constraints.

    Args:
        config: Configuration dictionary to validate

    Returns:
        List of validation errors (empty if valid)

    Example:
        >>> errors = validate_values({"PingCount": 150})
        >>> errors
        ['Field PingCount: value 150 exceeds maximum 100']
    """
    errors = []

    for field, constraints in VALUE_CONSTRAINTS.items():
        if field not in config:
            continue  # Optional field

        value = config[field]

        # Range constraints
        if "min" in constraints and isinstance(value, int):
            if value < constraints["min"]:
                errors.append(
                    f"Field {field}: value {value} below minimum {constraints['min']}"
                )

        if "max" in constraints and isinstance(value, int):
            if value > constraints["max"]:
                errors.append(
                    f"Field {field}: value {value} exceeds maximum {constraints['max']}"
                )

        # Enum constraints
        if "enum" in constraints:
            if value not in constraints["enum"]:
                errors.append(
                    f"Field {field}: invalid value '{value}', "
                    f"must be one of {constraints['enum']}"
                )

    return errors


def validate_security(config: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """
    Scan configuration for potential security issues.

    Args:
        config: Configuration dictionary to validate

    Returns:
        List of (field, issue_type, matched_pattern) tuples

    Example:
        >>> issues = validate_security({"ModemAddress": "'; DROP TABLE--"})
        >>> issues
        [('ModemAddress', 'sql_injection', 'DROP')]
    """
    issues = []

    # Only scan string fields
    for field, value in config.items():
        if not isinstance(value, str):
            continue

        # Skip obviously safe fields (these are never used in contexts where injection matters)
        safe_fields = {"CloudAPIKey", "IgnitePassword"}  # Secrets, not commands/queries
        if field in safe_fields:
            continue

        # Check each security pattern category
        for issue_type, patterns in SECURITY_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, value, re.IGNORECASE)
                if match:
                    issues.append((field, issue_type, match.group(0)))

    return issues


def validate_urls(config: Dict[str, Any]) -> List[str]:
    """
    Validate URL-like fields (format only, no network check).

    Args:
        config: Configuration dictionary to validate

    Returns:
        List of validation errors (empty if valid)

    Example:
        >>> errors = validate_urls({"CloudHost": "not a valid:url:123"})
        >>> errors
        ['Field CloudHost: invalid hostname format']
    """
    errors = []

    # CloudHost validation
    if "CloudHost" in config:
        host = config["CloudHost"]
        if host:
            # Simple hostname/IP validation
            # Allow: alphanumeric, dots, hyphens (DNS), or IPv4/IPv6
            if not re.match(r'^[a-zA-Z0-9.-]+$', host) and not re.match(r'^\[.*\]$', host):
                errors.append(f"Field CloudHost: invalid hostname format")

    # CloudPort validation (strict)
    if "CloudPort" in config:
        port = config["CloudPort"]
        if port:
            # Must be digits only (no whitespace, decimals, or other characters)
            if not isinstance(port, str) or not port.isdigit():
                errors.append(f"Field CloudPort: must be numeric string (got '{port}')")
            else:
                port_int = int(port)
                if port_int < 1 or port_int > 65535:
                    errors.append(f"Field CloudPort: port {port_int} out of range (1-65535)")

    # CloudPath validation (basic - prevent absolute paths)
    if "CloudPath" in config:
        path = config["CloudPath"]
        if path and path.startswith("/"):
            errors.append(f"Field CloudPath: absolute paths not allowed")

    return errors


async def test_url_reachability(
    config: Dict[str, Any],
    timeout_seconds: int = 5
) -> Dict[str, Any]:
    """
    Test if CloudHost is reachable (optional validation step).

    This is resource-intensive and should only be used during admin
    configuration updates, not during client syncs.

    Args:
        config: Configuration dictionary
        timeout_seconds: HTTP request timeout

    Returns:
        Dict with reachability results:
        {
            "reachable": bool,
            "status_code": int | None,
            "error": str | None,
            "latency_ms": float | None
        }

    Example:
        >>> result = await test_url_reachability({"CloudHost": "example.com", "CloudPort": "443"})
        >>> result
        {'reachable': True, 'status_code': 200, 'latency_ms': 42.5}
    """
    # Lazy import aiohttp (optional dependency for reachability testing)
    try:
        import aiohttp
    except ImportError:
        return {
            "reachable": False,
            "status_code": None,
            "error": "aiohttp not installed (optional dependency)",
            "latency_ms": None
        }

    if not config.get("EnableCloud"):
        return {"reachable": None, "error": "Cloud disabled", "status_code": None}

    host = config.get("CloudHost")
    port = config.get("CloudPort")

    if not host or not port:
        return {"reachable": False, "error": "Missing CloudHost or CloudPort", "status_code": None}

    # Build URL
    enforce_https = config.get("EnforceHTTPS", True)
    scheme = "https" if enforce_https else "http"
    url = f"{scheme}://{host}:{port}/api/config/health"

    # Test reachability
    start_time = asyncio.get_event_loop().time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ssl=False if config.get("InsecureTLS") else None
            ) as response:
                latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000

                return {
                    "reachable": response.status < 500,
                    "status_code": response.status,
                    "error": None,
                    "latency_ms": round(latency_ms, 2)
                }

    except asyncio.TimeoutError:
        return {
            "reachable": False,
            "status_code": None,
            "error": f"Timeout after {timeout_seconds}s",
            "latency_ms": None
        }
    except aiohttp.ClientError as e:
        return {
            "reachable": False,
            "status_code": None,
            "error": f"Connection error: {str(e)}",
            "latency_ms": None
        }
    except Exception as e:
        return {
            "reachable": False,
            "status_code": None,
            "error": f"Unexpected error: {str(e)}",
            "latency_ms": None
        }


async def validate_config(
    config: Dict[str, Any],
    check_reachability: bool = False,
    strict_security: bool = True
) -> None:
    """
    Comprehensive configuration validation.

    Args:
        config: Configuration dictionary to validate
        check_reachability: If True, test CloudHost reachability (slow)
        strict_security: If True, reject configs with security issues

    Raises:
        ConfigValidationError: If validation fails

    Example:
        >>> await validate_config({"PingCount": 50, "UpdateChannel": "stable"})
        # Passes
        >>> await validate_config({"PingCount": 150})
        ConfigValidationError: Field PingCount: value 150 exceeds maximum 100
    """
    all_errors = []

    # 1. Schema validation
    schema_errors = validate_schema(config)
    all_errors.extend(schema_errors)

    # 2. Value validation
    value_errors = validate_values(config)
    all_errors.extend(value_errors)

    # 3. URL validation
    url_errors = validate_urls(config)
    all_errors.extend(url_errors)

    # 4. Security validation
    security_issues = validate_security(config)
    if security_issues:
        if strict_security:
            for field, issue_type, pattern in security_issues:
                all_errors.append(
                    f"Security issue in {field}: potential {issue_type} "
                    f"(pattern: {pattern[:20]}...)"
                )
        else:
            # Just log warnings, don't fail validation
            for field, issue_type, pattern in security_issues:
                logger.warning(
                    f"Security warning in config field '{field}': potential {issue_type} "
                    f"(pattern: {pattern[:20]}...)"
                )

    # Raise if any errors found
    if all_errors:
        raise ConfigValidationError(
            message=f"Configuration validation failed ({len(all_errors)} errors)",
            details={
                "errors": all_errors[:10],  # Limit to first 10 errors
                "total_errors": len(all_errors)
            }
        )

    # 5. Optional reachability check (expensive, admin-only)
    if check_reachability and config.get("EnableCloud"):
        reachability = await test_url_reachability(config)
        if not reachability["reachable"]:
            raise ConfigValidationError(
                message=f"Cloud server unreachable: {reachability['error']}",
                details={
                    "host": config.get("CloudHost"),
                    "port": config.get("CloudPort"),
                    "error": reachability["error"]
                }
            )


SENSITIVE_FIELDS = ["CloudAPIKey", "IgnitePassword"]
REDACTED_VALUE = "***REDACTED***"


def sanitize_config_for_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize configuration for safe display (redact secrets).

    Args:
        config: Configuration dictionary

    Returns:
        Sanitized copy with secrets redacted

    Example:
        >>> sanitize_config_for_display({"CloudAPIKey": "secret123", "PingCount": 25})
        {'CloudAPIKey': '***REDACTED***', 'PingCount': 25}
    """
    sanitized = config.copy()

    # Redact sensitive fields
    for field in SENSITIVE_FIELDS:
        if field in sanitized and sanitized[field]:
            sanitized[field] = REDACTED_VALUE

    return sanitized


def restore_redacted_fields(
    new_config: Dict[str, Any],
    existing_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Restore redacted fields from existing config.

    When admin saves a config with ***REDACTED*** values, this function
    restores the original values from the existing config to prevent
    accidentally overwriting secrets with the redaction placeholder.

    Args:
        new_config: New configuration (may contain ***REDACTED*** values)
        existing_config: Existing configuration with actual values

    Returns:
        Config with redacted fields restored from existing config

    Example:
        >>> restore_redacted_fields(
        ...     {"CloudAPIKey": "***REDACTED***", "PingCount": 30},
        ...     {"CloudAPIKey": "actual_secret", "PingCount": 25}
        ... )
        {'CloudAPIKey': 'actual_secret', 'PingCount': 30}
    """
    restored = new_config.copy()

    for field in SENSITIVE_FIELDS:
        if field in restored and restored[field] == REDACTED_VALUE:
            # Restore from existing config if available
            if field in existing_config:
                restored[field] = existing_config[field]

    return restored
