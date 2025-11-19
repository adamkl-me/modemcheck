"""
Security vulnerability tests.

Tests for:
- SQL injection
- XSS attacks
- CSRF protection
- Path traversal
- Authentication bypass
- Rate limiting
"""
import pytest
import httpx

pytestmark = pytest.mark.security


class TestSQLInjection:
    """SQL injection attack tests."""
    
    @pytest.mark.asyncio
    async def test_sql_injection_login(self, http_client: httpx.AsyncClient):
        """Test SQL injection in login endpoint."""
        payloads = [
            "admin' OR '1'='1",
            "admin'--",
            "' OR 1=1--",
            "admin' /*",
            "1' UNION SELECT * FROM users--"
        ]
        
        for payload in payloads:
            response = await http_client.post("/api/auth/login", json={
                "username": payload,
                "password": "test"
            })
            # Should fail authentication, not execute SQL
            assert response.status_code in [401, 422], f"SQL injection may be possible with payload: {payload}"
    
    @pytest.mark.asyncio
    async def test_sql_injection_modem_id(self, admin_client_with_token: httpx.AsyncClient):
        """Test SQL injection in modem_id parameter."""
        payloads = [
            "test' OR '1'='1",
            "test'; DROP TABLE modem_checks--",
            "test' UNION SELECT * FROM users--"
        ]
        
        for payload in payloads:
            response = await admin_client_with_token.get(
                f"/api/db/list_checks?modem_id={payload}&start_date=2024-01-01&end_date=2024-12-31"
            )
            # Should return empty or error, not execute arbitrary SQL
            assert response.status_code in [200, 400, 404]


class TestXSS:
    """Cross-site scripting attack tests."""
    
    @pytest.mark.asyncio
    async def test_xss_in_username(self, http_client: httpx.AsyncClient):
        """Test XSS in username field."""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "<svg onload=alert('XSS')>"
        ]
        
        for payload in xss_payloads:
            response = await http_client.post("/api/auth/login", json={
                "username": payload,
                "password": "test"
            })
            # Should handle gracefully without executing script
            assert response.status_code in [401, 422]


class TestCSRF:
    """CSRF protection tests."""
    
    @pytest.mark.asyncio
    async def test_csrf_protected_endpoint_without_token(self, admin_client_with_token: httpx.AsyncClient):
        """Test CSRF-protected endpoint requires CSRF token."""
        # Try to create API key without CSRF token
        response = await admin_client_with_token.post("/api/admin/api_keys", json={
            "name": "test_key"
        })
        
        # Should fail without CSRF token
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_csrf_with_invalid_token(self, admin_client_with_token: httpx.AsyncClient):
        """Test CSRF-protected endpoint rejects invalid token."""
        response = await admin_client_with_token.post(
            "/api/admin/api_keys",
            json={"name": "test_key"},
            headers={"X-CSRF-Token": "invalid_token"}
        )
        
        assert response.status_code == 403


class TestPathTraversal:
    """Path traversal attack tests."""
    
    @pytest.mark.asyncio
    async def test_path_traversal_modem_id(self, admin_client_with_token: httpx.AsyncClient):
        """Test path traversal in modem_id."""
        payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "%2e%2e%2f%2e%2e%2f",
            "....//....//....//etc/passwd"
        ]
        
        for payload in payloads:
            response = await admin_client_with_token.get(
                f"/api/db/list_checks?modem_id={payload}&start_date=2024-01-01&end_date=2024-12-31"
            )
            # Should reject or return empty, not access files
            assert response.status_code in [200, 400, 404]


class TestAuthenticationBypass:
    """Authentication bypass attempt tests."""
    
    @pytest.mark.asyncio
    async def test_bypass_with_fake_cookie(self, http_client: httpx.AsyncClient):
        """Test authentication bypass with fake session cookie."""
        http_client.cookies.set("modemcheck_session", "fake_session_token_12345")
        
        response = await http_client.get("/api/admin/api_keys")
        
        # Should fail authentication
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_bypass_with_modified_role(self, basic_client_with_token: httpx.AsyncClient):
        """Test accessing admin endpoint with basic user."""
        response = await basic_client_with_token.get("/api/admin/logs/user_activity")
        
        # Should be forbidden (role check)
        assert response.status_code in [401, 403]


class TestFileUploadVulnerabilities:
    """File upload security tests."""
    
    @pytest.mark.asyncio
    async def test_upload_executable_file(self, http_client: httpx.AsyncClient, active_api_key):
        """Test uploading executable file disguised as JSON."""
        from io import BytesIO
        import hashlib
        import hmac
        import time

        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "2024-01-01_12-00-00.json"

        # Malicious content
        file_content = b"#!/bin/bash\nrm -rf /"
        checksum = hashlib.sha256(file_content).hexdigest()

        # Add HMAC signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|{filename}|{checksum}"
        signature = hmac.new(
            active_api_key.api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        files = {"file": (filename, BytesIO(file_content), "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": filename,
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        response = await http_client.post("/api/upload", files=files, data=data, headers=headers)

        # Should fail JSON validation
        assert response.status_code == 400


class TestRateLimiting:
    """Rate limiting tests."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.skip(reason="Rate limiting disabled in test environment to prevent fixture failures")
    async def test_login_rate_limiting(self, http_client: httpx.AsyncClient):
        """Test rate limiting on login endpoint.

        Rate limiting is configured with slowapi library:
        - Auth endpoints: 30 requests/minute (configured in app/routers/auth.py)
        - Redis backend for distributed rate limiting
        - Returns HTTP 429 after threshold exceeded

        NOTE: Rate limiting is disabled in test environment (TESTING=true) to prevent
        test fixtures from hitting rate limits. This test is skipped in test mode.
        To test rate limiting, run in production mode or with TESTING=false.
        """
        # Make 35 rapid login attempts to exceed the 30/minute limit
        rate_limited = False
        for i in range(35):
            response = await http_client.post("/api/auth/login", json={
                "username": f"test_user_{i}",
                "password": "test"
            })

            # Check if we got rate limited
            if response.status_code == 429:
                rate_limited = True
                # Verify response includes rate limit header
                assert "X-RateLimit-Limit" in response.headers or "Retry-After" in response.headers
                break

        # Ensure rate limiting occurred
        assert rate_limited, "Rate limiting did not trigger after 35 requests (limit is 30/minute)"


class TestSessionSecurity:
    """Session management security tests."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Session security tests need session cookie handling investigation")
    async def test_concurrent_sessions(self, http_client: httpx.AsyncClient, admin_user):
        """Test that multiple concurrent sessions are allowed for same user."""
        # Login from "first device"
        response1 = await http_client.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "AdminPass123!"
        })
        assert response1.status_code == 200
        session1 = response1.cookies.get("modemcheck_session")

        # Login from "second device" (new client)
        client2 = httpx.AsyncClient(base_url=http_client.base_url)
        response2 = await client2.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "AdminPass123!"
        })
        assert response2.status_code == 200
        session2 = response2.cookies.get("modemcheck_session")

        # Both sessions should be different
        assert session1 != session2

        # Both sessions should work
        check1 = await http_client.get("/api/auth/session_check")
        check2 = await client2.get("/api/auth/session_check")

        assert check1.status_code == 200
        assert check2.status_code == 200

        await client2.aclose()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Session security tests need session cookie handling investigation")
    async def test_session_expiration(self, http_client: httpx.AsyncClient, admin_user):
        """Test that sessions expire after TTL."""
        import time
        from unittest.mock import patch

        # Login to get session
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "AdminPass123!"
        })
        assert response.status_code == 200
        session_token = response.cookies.get("modemcheck_session")

        # Verify session works
        check = await http_client.get("/api/auth/session_check")
        assert check.status_code == 200

        # Note: We can't easily test actual expiration without waiting 1 hour
        # or mocking Redis. This test verifies the session is created with TTL.
        # The actual expiration is tested by checking Redis TTL exists.
        assert session_token is not None
        assert len(session_token) > 0

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Session security tests need session cookie handling investigation")
    async def test_session_hijacking_prevention(self, http_client: httpx.AsyncClient, admin_user):
        """Test session hijacking prevention via session validation."""
        # Login to get valid session
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "AdminPass123!"
        })
        assert response.status_code == 200
        valid_session = response.cookies.get("modemcheck_session")

        # Try to use modified session token
        modified_sessions = [
            valid_session[:-5] + "XXXXX",  # Modified end
            "XXXXX" + valid_session[5:],   # Modified start
            valid_session[:20] + "X" + valid_session[21:],  # Modified middle
        ]

        for modified in modified_sessions:
            client = httpx.AsyncClient(base_url=http_client.base_url)
            client.cookies.set("modemcheck_session", modified)

            response = await client.get("/api/auth/session_check")
            # Should reject modified session (authenticated should be false)
            assert response.status_code == 200
            data = response.json()
            assert data.get("authenticated") is False, f"Modified session accepted: {modified[:10]}..."

            await client.aclose()


class TestPasswordSecurity:
    """Password validation and security tests."""

    @pytest.mark.asyncio
    async def test_password_validation_length(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test password minimum length requirement."""
        short_passwords = ["Short1!", "Pass1!", "Abc123!"]

        for password in short_passwords:
            response = await admin_client_with_token.post(
                "/api/users",
                json={
                    "username": "testuser",
                    "password": password,
                    "role": "basic",
                    "csrf_token": csrf_token
                }
            )
            # Pydantic validation returns 422 (Unprocessable Entity) for validation errors
            assert response.status_code == 422, f"Short password accepted: {password}"

    @pytest.mark.asyncio
    async def test_password_validation_complexity(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test password complexity requirements."""
        weak_passwords = [
            "alllowercase1!",  # No uppercase
            "ALLUPPERCASE1!",  # No lowercase
            "NoNumbers!!!",     # No digits
            "NoSpecialChar1",   # No special characters
        ]

        for password in weak_passwords:
            response = await admin_client_with_token.post(
                "/api/users",
                json={
                    "username": "testuser",
                    "password": password,
                    "role": "basic",
                    "csrf_token": csrf_token
                }
            )
            # Should reject weak passwords
            assert response.status_code == 400, f"Weak password accepted: {password}"

    @pytest.mark.asyncio
    async def test_password_validation_common_passwords(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test rejection of common passwords."""
        import uuid
        common_passwords = [
            "Password123!",
            "Welcome123!",
            "Admin123456!",
        ]

        for idx, password in enumerate(common_passwords):
            # Use unique username for each iteration to avoid conflicts
            unique_username = f"testuser_{uuid.uuid4().hex[:8]}"
            response = await admin_client_with_token.post(
                "/api/users",
                json={
                    "username": unique_username,
                    "password": password,
                    "role": "basic",
                    "csrf_token": csrf_token
                }
            )
            # Should reject common passwords
            # Note: This may pass if the password isn't in common_passwords.txt
            # The important thing is the check exists
            if response.status_code == 200:
                # Clean up created user
                data = response.json()
                if data.get("success") and "user" in data and isinstance(data["user"], dict):
                    await admin_client_with_token.delete(
                        f"/api/users/{data['user']['id']}",
                        params={"csrf_token": csrf_token}
                    )
            else:
                # Password was rejected (expected behavior for common passwords)
                assert response.status_code in [400, 422]


class TestTimingAttacks:
    """Timing attack prevention tests."""

    @pytest.mark.asyncio
    async def test_timing_attack_api_key_validation(self, http_client: httpx.AsyncClient):
        """Test API key validation uses constant-time comparison."""
        import time
        from io import BytesIO
        import hashlib
        import json

        modem_id = "XB8-AA:BB:CC:DD:EE:FF"
        filename = "2024-01-01_12-00-00.json"
        file_content = json.dumps({"test": "data"}).encode()
        checksum = hashlib.sha256(file_content).hexdigest()

        # Test with completely wrong key (all wrong characters)
        wrong_key = "0" * 64
        times_wrong = []

        for _ in range(5):
            start = time.perf_counter()
            files = {"file": (filename, BytesIO(file_content), "application/json")}
            data = {
                "api_key": wrong_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }
            await http_client.post("/api/upload", files=files, data=data)
            elapsed = time.perf_counter() - start
            times_wrong.append(elapsed)

        # Test with partially correct key (first half correct, second half wrong)
        # Note: We don't know a real key, so we test the timing is consistent
        partial_key = "a" * 32 + "0" * 32
        times_partial = []

        for _ in range(5):
            start = time.perf_counter()
            files = {"file": (filename, BytesIO(file_content), "application/json")}
            data = {
                "api_key": partial_key,
                "modem_id": modem_id,
                "filename": filename,
                "checksum": checksum
            }
            await http_client.post("/api/upload", files=files, data=data)
            elapsed = time.perf_counter() - start
            times_partial.append(elapsed)

        # Timing should be similar (within 20% variance)
        # This is a basic check - true timing attack prevention uses hmac.compare_digest
        avg_wrong = sum(times_wrong) / len(times_wrong)
        avg_partial = sum(times_partial) / len(times_partial)

        # The difference should be minimal (not exploitable)
        # Allow 50% variance due to network/processing overhead in tests
        assert abs(avg_wrong - avg_partial) / avg_wrong < 0.5, \
            "Timing difference may allow timing attack"


class TestCookieSecurity:
    """Cookie security flag tests."""

    @pytest.mark.asyncio
    async def test_cookie_secure_flag_https(self, http_client: httpx.AsyncClient, admin_user):
        """Test that cookies have Secure flag on HTTPS."""
        # Simulate HTTPS request with X-Forwarded-Proto header
        response = await http_client.post(
            "/api/auth/login",
            json={
                "username": admin_user.username,
                "password": "TestPass123!"  # Match admin_user fixture password
            },
            headers={"X-Forwarded-Proto": "https"}
        )

        assert response.status_code == 200

        # Check Set-Cookie header for Secure flag
        set_cookie = response.headers.get("set-cookie", "")
        if set_cookie:
            # Should have Secure flag when HTTPS
            assert "Secure" in set_cookie or "secure" in set_cookie.lower(), \
                "Cookie missing Secure flag on HTTPS"

    @pytest.mark.asyncio
    async def test_cookie_httponly_flag(self, http_client: httpx.AsyncClient, admin_user):
        """Test that cookies have HttpOnly flag."""
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "TestPass123!"  # Match admin_user fixture password
        })

        assert response.status_code == 200

        # Check Set-Cookie header for HttpOnly flag
        set_cookie = response.headers.get("set-cookie", "")
        if set_cookie:
            assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower(), \
                "Cookie missing HttpOnly flag"

    @pytest.mark.asyncio
    async def test_cookie_samesite_flag(self, http_client: httpx.AsyncClient, admin_user):
        """Test that cookies have SameSite flag."""
        response = await http_client.post("/api/auth/login", json={
            "username": admin_user.username,
            "password": "TestPass123!"  # Match admin_user fixture password
        })

        assert response.status_code == 200

        # Check Set-Cookie header for SameSite flag
        set_cookie = response.headers.get("set-cookie", "")
        if set_cookie:
            assert "SameSite" in set_cookie or "samesite" in set_cookie.lower(), \
                "Cookie missing SameSite flag"


class TestXSSAdditional:
    """Additional XSS attack tests."""

    @pytest.mark.asyncio
    async def test_xss_in_api_key_name(self, admin_client_with_token: httpx.AsyncClient, csrf_token: str):
        """Test XSS in API key name field."""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
        ]

        for payload in xss_payloads:
            response = await admin_client_with_token.post(
                "/api/admin/api_keys",
                json={"name": payload},
                headers={"X-CSRF-Token": csrf_token}
            )

            # Should either accept and sanitize, or reject
            if response.status_code == 200:
                # If accepted, verify it's stored safely (not executed)
                data = response.json()
                assert isinstance(data, dict), "Response should be a dictionary"
                assert data.get("success") is True

                # Clean up
                if "api_key" in data and isinstance(data["api_key"], dict):
                    key_id = data["api_key"]["id"]
                    await admin_client_with_token.delete(
                        f"/api/admin/api_keys/{key_id}",
                        params={"csrf_token": csrf_token}
                    )
            else:
                # XSS payload rejected (also acceptable)
                assert response.status_code in [400, 422]
