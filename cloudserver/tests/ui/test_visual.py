"""
Visual Regression Tests for ModemCheck Cloud UI.

Uses Playwright's built-in screenshot comparison for visual regression testing.
Screenshots are stored in tests/ui/screenshots/ directory.
"""
import pytest
from pathlib import Path
from playwright.async_api import Page, expect

from tests.ui.pages import LoginPage, AdminPage, ViewerPage, ForbiddenPage

pytestmark = [pytest.mark.ui, pytest.mark.visual]

# Test server URL
BASE_URL = "http://localhost:23894"

# Screenshot directory
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


# =============================================================================
# ENSURE SCREENSHOT DIRECTORY EXISTS
# =============================================================================

@pytest.fixture(scope="module", autouse=True)
def ensure_screenshot_dir():
    """Ensure screenshot directory exists."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    yield


# =============================================================================
# LOGIN PAGE VISUAL TESTS
# =============================================================================

class TestLoginVisual:
    """Visual regression tests for the login page."""

    @pytest.mark.asyncio
    async def test_login_page_dark_theme_screenshot(self, browser_page: Page):
        """Capture login page in dark theme."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Ensure dark theme
        await login_page.set_theme("dark")
        await browser_page.wait_for_timeout(300)

        # Take screenshot
        await expect(browser_page).to_have_screenshot(
            "login-dark.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_login_page_light_theme_screenshot(self, browser_page: Page):
        """Capture login page in light theme."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Switch to light theme
        await login_page.set_theme("light")
        await browser_page.wait_for_timeout(300)

        # Take screenshot
        await expect(browser_page).to_have_screenshot(
            "login-light.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_login_error_state_screenshot(self, browser_page: Page):
        """Capture login page with error message."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Trigger an error
        await login_page.login("invalid_user", "invalid_password")
        await browser_page.wait_for_timeout(1000)

        # Only take screenshot if error is visible
        if await login_page.is_error_visible():
            await expect(browser_page).to_have_screenshot(
                "login-error.png",
                threshold=0.2,
                full_page=True
            )


# =============================================================================
# VIEWER PAGE VISUAL TESTS
# =============================================================================

class TestViewerVisual:
    """Visual regression tests for the viewer page."""

    @pytest.mark.asyncio
    async def test_viewer_empty_state_dark(self, browser_page: Page):
        """Viewer page with no data selected (dark theme)."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        await viewer_page.set_theme("dark")
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "viewer-empty-dark.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_viewer_empty_state_light(self, browser_page: Page):
        """Viewer page with no data selected (light theme)."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        await viewer_page.set_theme("light")
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "viewer-empty-light.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_viewer_with_modem_dropdown_open(self, browser_page: Page):
        """Viewer page with modem dropdown open."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)

        # Open modem dropdown
        await viewer_page.modem_search_input.click()
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "viewer-dropdown-open.png",
            threshold=0.2,
            full_page=True
        )


# =============================================================================
# ADMIN PAGE VISUAL TESTS
# =============================================================================

class TestAdminVisual:
    """Visual regression tests for the admin page."""

    @pytest.mark.asyncio
    async def test_admin_dashboard_dark(self, browser_page: Page):
        """Admin dashboard in dark theme."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.set_theme("dark")
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "admin-dashboard-dark.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_admin_dashboard_light(self, browser_page: Page):
        """Admin dashboard in light theme."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.set_theme("light")
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "admin-dashboard-light.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_admin_users_tab(self, browser_page: Page):
        """Admin users tab screenshot."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.click_tab("users")
        await browser_page.wait_for_timeout(500)

        await expect(browser_page).to_have_screenshot(
            "admin-users-tab.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_admin_modal_screenshot(self, browser_page: Page):
        """Admin page with modal open."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.open_create_api_key_modal()
        await browser_page.wait_for_timeout(500)

        if await admin_page.is_new_key_modal_visible():
            await expect(browser_page).to_have_screenshot(
                "admin-modal-open.png",
                threshold=0.2,
                full_page=True
            )


# =============================================================================
# FORBIDDEN PAGE VISUAL TESTS
# =============================================================================

class TestForbiddenVisual:
    """Visual regression tests for the forbidden page."""

    @pytest.mark.asyncio
    async def test_forbidden_dark(self, browser_page: Page):
        """Forbidden page in dark theme."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()
        await forbidden_page.set_theme("dark")
        await browser_page.wait_for_timeout(300)

        await expect(browser_page).to_have_screenshot(
            "forbidden-dark.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_forbidden_light(self, browser_page: Page):
        """Forbidden page in light theme."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()
        await forbidden_page.set_theme("light")
        await browser_page.wait_for_timeout(300)

        await expect(browser_page).to_have_screenshot(
            "forbidden-light.png",
            threshold=0.2,
            full_page=True
        )


# =============================================================================
# MOBILE VISUAL TESTS
# =============================================================================

class TestMobileVisual:
    """Visual regression tests for mobile viewports."""

    @pytest.mark.asyncio
    async def test_login_mobile_screenshot(self, mobile_page: Page):
        """Login page on mobile viewport."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()

        await expect(mobile_page).to_have_screenshot(
            "login-mobile.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_admin_mobile_hamburger(self, mobile_page: Page):
        """Admin page on mobile with hamburger menu."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()
        await mobile_page.wait_for_timeout(500)

        await expect(mobile_page).to_have_screenshot(
            "admin-mobile.png",
            threshold=0.2,
            full_page=True
        )

    @pytest.mark.asyncio
    async def test_admin_mobile_menu_open(self, mobile_page: Page):
        """Admin page on mobile with menu open."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.open_mobile_menu()
        await mobile_page.wait_for_timeout(300)

        await expect(mobile_page).to_have_screenshot(
            "admin-mobile-menu-open.png",
            threshold=0.2,
            full_page=True
        )
