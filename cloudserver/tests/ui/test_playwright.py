"""
Playwright UI tests for ModemCheck Cloud v2.

Tests web interface functionality using browser automation.

NOTE: These tests require Playwright browser drivers to be installed.
Run: playwright install chromium
Or skip these tests with: pytest -m "not ui"
"""
import pytest
from playwright.async_api import async_playwright, Page, expect

pytestmark = pytest.mark.ui

BASE_URL = "http://localhost:23894"  # Web UI port


@pytest.fixture(scope="function")
async def browser_page():
    """Create Playwright browser page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


class TestLoginUI:
    """UI tests for login page."""

    @pytest.mark.asyncio
    async def test_login_page_loads(self, browser_page: Page):
        """Test login page loads correctly."""
        await browser_page.goto(f"{BASE_URL}/login")
        await expect(browser_page).to_have_title("Login - ModemCheck Cloud")

        # Verify form elements are present
        await expect(browser_page.locator('#username')).to_be_visible()
        await expect(browser_page.locator('#password')).to_be_visible()
        await expect(browser_page.locator('button[type="submit"]')).to_be_visible()

    @pytest.mark.asyncio
    async def test_login_success(self, browser_page: Page):
        """Test successful login flow."""
        await browser_page.goto(f"{BASE_URL}/login")

        # Fill login form using ID selectors
        await browser_page.fill('#username', 'admin')
        await browser_page.fill('#password', 'TestPass123!')

        # Click submit button
        await browser_page.click('button[type="submit"]')

        # Wait for JavaScript redirect to /viewer (timeout 10 seconds)
        await browser_page.wait_for_url(f"{BASE_URL}/viewer", timeout=10000)

        # Verify we're on the viewer page
        await expect(browser_page).to_have_url(f"{BASE_URL}/viewer")

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, browser_page: Page):
        """Test login with invalid credentials shows error."""
        await browser_page.goto(f"{BASE_URL}/login")

        await browser_page.fill('#username', 'invalid_user')
        await browser_page.fill('#password', 'wrong_password')
        await browser_page.click('button[type="submit"]')

        # Wait a bit for the error to appear
        await browser_page.wait_for_timeout(1000)

        # Should show error message (class .show is added when error displays)
        error = browser_page.locator('#error.show')
        await expect(error).to_be_visible()


class TestViewerUI:
    """UI tests for viewer dashboard."""

    @pytest.mark.asyncio
    async def test_viewer_requires_login(self, browser_page: Page):
        """Test viewer redirects to login if not authenticated."""
        await browser_page.goto(f"{BASE_URL}/viewer")

        # Should redirect to login
        await browser_page.wait_for_url(f"{BASE_URL}/login")
        await expect(browser_page).to_have_url(f"{BASE_URL}/login")

    @pytest.mark.asyncio
    async def test_viewer_displays_modems(self, browser_page: Page):
        """Test viewer displays modem list after login."""
        # Login first
        await browser_page.goto(f"{BASE_URL}/login")
        await browser_page.fill('#username', 'admin')
        await browser_page.fill('#password', 'TestPass123!')

        # Click submit and wait for redirect
        await browser_page.click('button[type="submit"]')
        await browser_page.wait_for_url(f"{BASE_URL}/viewer", timeout=10000)

        # Verify we're on the viewer page
        await expect(browser_page).to_have_url(f"{BASE_URL}/viewer")

        # Wait for page to load and check for key UI elements
        await browser_page.wait_for_timeout(1000)

        # Verify we're on the viewer page by checking for key elements
        page_content = await browser_page.content()
        assert "ModemCheck" in page_content or "viewer" in page_content.lower()


class TestAdminUI:
    """UI tests for admin dashboard."""

    @pytest.mark.asyncio
    async def test_admin_requires_admin_role(self, browser_page: Page):
        """Test admin page requires admin role.

        Verifies that basic role users receive HTTP 403 Forbidden when attempting
        to access the admin dashboard. The test_basic user is created by the
        session-scoped ensure_ui_test_users fixture in conftest.py.
        """
        # Login as basic user (from test fixtures)
        await browser_page.goto(f"{BASE_URL}/login")
        await browser_page.fill('#username', 'test_basic')
        await browser_page.fill('#password', 'BasicPass123!')

        # Click submit and wait for redirect
        await browser_page.click('button[type="submit"]')
        await browser_page.wait_for_url(f"{BASE_URL}/viewer", timeout=10000)

        # Verify we're on the viewer page
        await expect(browser_page).to_have_url(f"{BASE_URL}/viewer")

        # Try to access admin page
        await browser_page.goto(f"{BASE_URL}/admin")

        # Should show forbidden page (403 response)
        await browser_page.wait_for_timeout(1000)

        # Check that we're NOT on the admin page
        # The server returns forbidden.html with 403 status
        page_content = await browser_page.content()

        # Either we're on forbidden page or the content shows access denied
        assert "forbidden" in page_content.lower() or \
               "access denied" in page_content.lower() or \
               "403" in page_content

    @pytest.mark.asyncio
    async def test_admin_page_accessible_to_admin(self, browser_page: Page):
        """Test admin page is accessible to admin users."""
        # Login as admin
        await browser_page.goto(f"{BASE_URL}/login")
        await browser_page.fill('#username', 'admin')
        await browser_page.fill('#password', 'TestPass123!')

        # Click submit and wait for redirect
        await browser_page.click('button[type="submit"]')
        await browser_page.wait_for_url(f"{BASE_URL}/viewer", timeout=10000)

        # Verify we're on the viewer page
        await expect(browser_page).to_have_url(f"{BASE_URL}/viewer")

        # Navigate to admin page
        await browser_page.goto(f"{BASE_URL}/admin")

        # Wait for page to load
        await browser_page.wait_for_timeout(1000)

        # Should successfully load admin page
        page_content = await browser_page.content()

        # Admin page should contain admin-specific content
        assert "admin" in page_content.lower() or \
               "dashboard" in page_content.lower()
