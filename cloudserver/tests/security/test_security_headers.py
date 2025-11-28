"""
Tests for security headers middleware.

Tests HTTP security headers are properly added to all responses:
- Strict-Transport-Security (HSTS)
- X-Content-Type-Options
- X-Frame-Options
- X-XSS-Protection
- Content-Security-Policy (CSP)
- Referrer-Policy
- Permissions-Policy
"""
import pytest
import httpx

pytestmark = pytest.mark.security


class TestXContentTypeOptionsHeader:
    """Tests for X-Content-Type-Options header (prevents MIME sniffing)."""

    @pytest.mark.asyncio
    async def test_x_content_type_options_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-Content-Type-Options header is present."""
        response = await http_client.get("/api/config/health")

        assert "X-Content-Type-Options" in response.headers

    @pytest.mark.asyncio
    async def test_x_content_type_options_value_nosniff(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-Content-Type-Options is set to nosniff."""
        response = await http_client.get("/api/config/health")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestXFrameOptionsHeader:
    """Tests for X-Frame-Options header (prevents clickjacking)."""

    @pytest.mark.asyncio
    async def test_x_frame_options_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-Frame-Options header is present."""
        response = await http_client.get("/api/config/health")

        assert "X-Frame-Options" in response.headers

    @pytest.mark.asyncio
    async def test_x_frame_options_value_deny(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-Frame-Options is set to DENY."""
        response = await http_client.get("/api/config/health")

        assert response.headers.get("X-Frame-Options") == "DENY"


class TestXXSSProtectionHeader:
    """Tests for X-XSS-Protection header (legacy XSS protection)."""

    @pytest.mark.asyncio
    async def test_x_xss_protection_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-XSS-Protection header is present."""
        response = await http_client.get("/api/config/health")

        assert "X-XSS-Protection" in response.headers

    @pytest.mark.asyncio
    async def test_x_xss_protection_value(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-XSS-Protection is set to 1; mode=block."""
        response = await http_client.get("/api/config/health")

        assert response.headers.get("X-XSS-Protection") == "1; mode=block"


class TestHSTSHeader:
    """Tests for Strict-Transport-Security header (HSTS)."""

    @pytest.mark.asyncio
    async def test_hsts_present_in_test_mode(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test HSTS header is present in test mode."""
        response = await http_client.get("/api/config/health")

        # In test mode, HSTS should always be present for verification
        assert "Strict-Transport-Security" in response.headers

    @pytest.mark.asyncio
    async def test_hsts_includes_max_age(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test HSTS includes max-age directive."""
        response = await http_client.get("/api/config/health")

        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts

    @pytest.mark.asyncio
    async def test_hsts_max_age_at_least_one_year(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test HSTS max-age is at least one year (31536000 seconds)."""
        response = await http_client.get("/api/config/health")

        hsts = response.headers.get("Strict-Transport-Security", "")
        # Extract max-age value
        import re
        match = re.search(r'max-age=(\d+)', hsts)
        if match:
            max_age = int(match.group(1))
            assert max_age >= 31536000, f"HSTS max-age should be at least 1 year, got {max_age}"

    @pytest.mark.asyncio
    async def test_hsts_includes_subdomains(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test HSTS includes includeSubDomains directive."""
        response = await http_client.get("/api/config/health")

        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "includeSubDomains" in hsts

    @pytest.mark.asyncio
    async def test_hsts_includes_preload(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test HSTS includes preload directive for browser preload lists."""
        response = await http_client.get("/api/config/health")

        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "preload" in hsts


class TestContentSecurityPolicyHeader:
    """Tests for Content-Security-Policy header (CSP)."""

    @pytest.mark.asyncio
    async def test_csp_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Content-Security-Policy header is present."""
        response = await http_client.get("/api/config/health")

        assert "Content-Security-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_csp_default_src_self(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP has default-src 'self' directive."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_script_src(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP has script-src directive."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "script-src" in csp

    @pytest.mark.asyncio
    async def test_csp_style_src(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP has style-src directive."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "style-src" in csp

    @pytest.mark.asyncio
    async def test_csp_frame_ancestors_none(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP prevents framing with frame-ancestors 'none'."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_csp_form_action_self(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP restricts form submissions to same origin."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "form-action 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_base_uri_self(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP restricts base URI to same origin."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "base-uri 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_upgrade_insecure_requests(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test CSP includes upgrade-insecure-requests directive."""
        response = await http_client.get("/api/config/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "upgrade-insecure-requests" in csp


class TestReferrerPolicyHeader:
    """Tests for Referrer-Policy header."""

    @pytest.mark.asyncio
    async def test_referrer_policy_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Referrer-Policy header is present."""
        response = await http_client.get("/api/config/health")

        assert "Referrer-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_referrer_policy_value(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Referrer-Policy is set to strict-origin-when-cross-origin."""
        response = await http_client.get("/api/config/health")

        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


class TestPermissionsPolicyHeader:
    """Tests for Permissions-Policy header (browser feature restrictions)."""

    @pytest.mark.asyncio
    async def test_permissions_policy_present(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Permissions-Policy header is present."""
        response = await http_client.get("/api/config/health")

        assert "Permissions-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_permissions_policy_disables_geolocation(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Permissions-Policy disables geolocation."""
        response = await http_client.get("/api/config/health")

        policy = response.headers.get("Permissions-Policy", "")
        assert "geolocation=()" in policy

    @pytest.mark.asyncio
    async def test_permissions_policy_disables_microphone(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Permissions-Policy disables microphone access."""
        response = await http_client.get("/api/config/health")

        policy = response.headers.get("Permissions-Policy", "")
        assert "microphone=()" in policy

    @pytest.mark.asyncio
    async def test_permissions_policy_disables_camera(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Permissions-Policy disables camera access."""
        response = await http_client.get("/api/config/health")

        policy = response.headers.get("Permissions-Policy", "")
        assert "camera=()" in policy

    @pytest.mark.asyncio
    async def test_permissions_policy_disables_payment(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Permissions-Policy disables payment request API."""
        response = await http_client.get("/api/config/health")

        policy = response.headers.get("Permissions-Policy", "")
        assert "payment=()" in policy


class TestServerHeaderRemoval:
    """Tests for removal of server identification headers."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Server header removal handled by nginx in production; test hits Uvicorn directly")
    async def test_server_header_removed(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test Server header is removed from responses.

        Note: In test mode, we hit the Python server directly (Uvicorn),
        which adds "Server: uvicorn". In production, nginx removes this header.
        This test is skipped in the test environment.
        """
        response = await http_client.get("/api/config/health")

        # Server header should be removed (security by obscurity)
        assert "Server" not in response.headers or response.headers.get("Server") == ""

    @pytest.mark.asyncio
    async def test_x_powered_by_header_removed(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test X-Powered-By header is removed from responses."""
        response = await http_client.get("/api/config/health")

        assert "X-Powered-By" not in response.headers


class TestSecurityHeadersOnAllEndpoints:
    """Tests that security headers are applied to all endpoint types."""

    @pytest.mark.asyncio
    async def test_security_headers_on_api_endpoint(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test security headers present on API endpoints."""
        response = await http_client.get("/api/config/health")

        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers
        assert "Content-Security-Policy" in response.headers

    @pytest.mark.asyncio
    async def test_security_headers_on_auth_endpoint(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test security headers present on auth endpoints."""
        response = await http_client.get("/api/auth/session_check")

        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers

    @pytest.mark.asyncio
    async def test_security_headers_on_error_response(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test security headers present on error responses."""
        # Request non-existent endpoint
        response = await http_client.get("/api/nonexistent_endpoint")

        # Even 404 responses should have security headers
        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers

    @pytest.mark.asyncio
    async def test_security_headers_on_post_request(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test security headers present on POST responses."""
        response = await http_client.post(
            "/api/auth/login",
            json={"username": "test", "password": "test"}
        )

        # Even failed auth should have security headers
        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers


class TestSecurityHeadersConsistency:
    """Tests for consistency of security headers across requests."""

    @pytest.mark.asyncio
    async def test_headers_consistent_across_requests(
        self,
        http_client: httpx.AsyncClient
    ):
        """Test security headers are consistent across multiple requests."""
        responses = []
        for _ in range(3):
            response = await http_client.get("/api/config/health")
            responses.append(response)

        # All responses should have identical security headers
        first_headers = {
            "X-Content-Type-Options": responses[0].headers.get("X-Content-Type-Options"),
            "X-Frame-Options": responses[0].headers.get("X-Frame-Options"),
            "Referrer-Policy": responses[0].headers.get("Referrer-Policy"),
        }

        for response in responses[1:]:
            assert response.headers.get("X-Content-Type-Options") == first_headers["X-Content-Type-Options"]
            assert response.headers.get("X-Frame-Options") == first_headers["X-Frame-Options"]
            assert response.headers.get("Referrer-Policy") == first_headers["Referrer-Policy"]
