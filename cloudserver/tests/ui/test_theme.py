"""
Dark/Light Mode Theme Tests for ModemCheck Cloud UI.

Tests theme toggle functionality, localStorage persistence, CSS property changes,
and cross-page theme persistence for all 4 pages (login, admin, viewer, forbidden).
"""
import pytest
from playwright.async_api import Page, expect

from tests.ui.pages import LoginPage, AdminPage, ViewerPage, ForbiddenPage

pytestmark = [pytest.mark.ui, pytest.mark.theme]

# Test server URL
BASE_URL = "http://localhost:23894"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def get_current_theme(page: Page) -> str:
    """Get current theme from data-theme attribute."""
    return await page.evaluate("document.documentElement.getAttribute('data-theme')")


async def get_stored_theme(page: Page) -> str:
    """Get theme from localStorage."""
    return await page.evaluate("localStorage.getItem('modemcheck-theme')")


async def get_background_color(page: Page) -> str:
    """Get computed background color of body."""
    return await page.evaluate("getComputedStyle(document.body).backgroundColor")


async def get_text_color(page: Page) -> str:
    """Get computed text color of body."""
    return await page.evaluate("getComputedStyle(document.body).color")


# =============================================================================
# LOGIN PAGE THEME TESTS
# =============================================================================

class TestLoginTheme:
    """Theme tests for the login page."""

    @pytest.mark.asyncio
    async def test_default_theme_is_dark(self, browser_page: Page):
        """Verify that the default theme is dark when no localStorage value exists."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        theme = await login_page.get_current_theme()
        assert theme == "dark", f"Expected default theme 'dark', got '{theme}'"

    @pytest.mark.asyncio
    async def test_toggle_button_changes_data_theme_attribute(self, browser_page: Page):
        """Verify clicking theme toggle changes data-theme attribute."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Get initial theme
        initial_theme = await login_page.get_current_theme()
        assert initial_theme == "dark"

        # Toggle theme
        await login_page.toggle_theme()

        # Verify theme changed
        new_theme = await login_page.get_current_theme()
        assert new_theme == "light", f"Expected 'light' after toggle, got '{new_theme}'"

        # Toggle back
        await login_page.toggle_theme()
        final_theme = await login_page.get_current_theme()
        assert final_theme == "dark", f"Expected 'dark' after second toggle, got '{final_theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_in_localstorage(self, browser_page: Page):
        """Verify theme choice is saved to localStorage."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Toggle to light theme
        await login_page.toggle_theme()

        # Check localStorage
        stored_theme = await login_page.get_stored_theme()
        assert stored_theme == "light", f"Expected 'light' in localStorage, got '{stored_theme}'"

    @pytest.mark.asyncio
    async def test_theme_restored_on_reload(self, browser_page: Page):
        """Verify theme is restored from localStorage on page reload."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Toggle to light theme
        await login_page.toggle_theme()
        assert await login_page.get_current_theme() == "light"

        # Reload page
        await browser_page.reload()
        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)

        # Verify theme is still light
        theme_after_reload = await login_page.get_current_theme()
        assert theme_after_reload == "light", f"Expected 'light' after reload, got '{theme_after_reload}'"

    @pytest.mark.asyncio
    async def test_css_properties_change_with_theme(self, browser_page: Page):
        """Verify CSS properties change when theme is toggled."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Get dark theme colors
        dark_bg = await login_page.get_background_color()
        dark_text = await login_page.get_text_color()

        # Toggle to light
        await login_page.toggle_theme()

        # Get light theme colors
        light_bg = await login_page.get_background_color()
        light_text = await login_page.get_text_color()

        # Colors should be different between themes
        assert dark_bg != light_bg, f"Background color should differ: dark={dark_bg}, light={light_bg}"
        assert dark_text != light_text, f"Text color should differ: dark={dark_text}, light={light_text}"

    @pytest.mark.asyncio
    async def test_theme_toggle_button_visible(self, browser_page: Page):
        """Verify theme toggle button is visible on login page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        assert await login_page.is_theme_toggle_visible(), "Theme toggle button should be visible"


# =============================================================================
# VIEWER PAGE THEME TESTS
# =============================================================================

class TestViewerTheme:
    """Theme tests for the viewer page (requires authentication)."""

    @pytest.mark.asyncio
    async def test_default_theme_is_dark(self, browser_page: Page):
        """Verify that the default theme is dark on viewer page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        theme = await viewer_page.get_current_theme()
        assert theme == "dark", f"Expected default theme 'dark', got '{theme}'"

    @pytest.mark.asyncio
    async def test_toggle_button_changes_data_theme_attribute(self, browser_page: Page):
        """Verify clicking theme toggle changes data-theme attribute on viewer."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)

        # Toggle theme
        await viewer_page.toggle_theme()

        # Verify theme changed
        new_theme = await viewer_page.get_current_theme()
        assert new_theme == "light", f"Expected 'light' after toggle, got '{new_theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_in_localstorage(self, browser_page: Page):
        """Verify theme choice is saved to localStorage on viewer page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        await viewer_page.toggle_theme()

        stored_theme = await viewer_page.get_stored_theme()
        assert stored_theme == "light", f"Expected 'light' in localStorage, got '{stored_theme}'"

    @pytest.mark.asyncio
    async def test_theme_restored_on_reload(self, browser_page: Page):
        """Verify theme is restored from localStorage on viewer page reload."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        await viewer_page.toggle_theme()
        assert await viewer_page.get_current_theme() == "light"

        # Reload page
        await browser_page.reload()
        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)

        theme_after_reload = await viewer_page.get_current_theme()
        assert theme_after_reload == "light", f"Expected 'light' after reload, got '{theme_after_reload}'"

    @pytest.mark.asyncio
    async def test_css_properties_change_with_theme(self, browser_page: Page):
        """Verify CSS properties change when theme is toggled on viewer."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)

        dark_bg = await viewer_page.get_background_color()
        await viewer_page.toggle_theme()
        light_bg = await viewer_page.get_background_color()

        assert dark_bg != light_bg, f"Background color should differ: dark={dark_bg}, light={light_bg}"

    @pytest.mark.asyncio
    async def test_theme_toggle_button_visible(self, browser_page: Page):
        """Verify theme toggle button is visible on viewer page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        assert await viewer_page.is_theme_toggle_visible(), "Theme toggle button should be visible"


# =============================================================================
# ADMIN PAGE THEME TESTS
# =============================================================================

class TestAdminTheme:
    """Theme tests for the admin page (requires admin authentication)."""

    @pytest.mark.asyncio
    async def test_default_theme_is_dark(self, browser_page: Page):
        """Verify that the default theme is dark on admin page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        theme = await admin_page.get_current_theme()
        assert theme == "dark", f"Expected default theme 'dark', got '{theme}'"

    @pytest.mark.asyncio
    async def test_toggle_button_changes_data_theme_attribute(self, browser_page: Page):
        """Verify clicking theme toggle changes data-theme attribute on admin."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        await admin_page.toggle_theme()

        new_theme = await admin_page.get_current_theme()
        assert new_theme == "light", f"Expected 'light' after toggle, got '{new_theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_in_localstorage(self, browser_page: Page):
        """Verify theme choice is saved to localStorage on admin page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.toggle_theme()

        stored_theme = await admin_page.get_stored_theme()
        assert stored_theme == "light", f"Expected 'light' in localStorage, got '{stored_theme}'"

    @pytest.mark.asyncio
    async def test_theme_restored_on_reload(self, browser_page: Page):
        """Verify theme is restored from localStorage on admin page reload."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.toggle_theme()
        assert await admin_page.get_current_theme() == "light"

        await browser_page.reload()
        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)

        theme_after_reload = await admin_page.get_current_theme()
        assert theme_after_reload == "light", f"Expected 'light' after reload, got '{theme_after_reload}'"

    @pytest.mark.asyncio
    async def test_css_properties_change_with_theme(self, browser_page: Page):
        """Verify CSS properties change when theme is toggled on admin."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        dark_bg = await admin_page.get_background_color()
        await admin_page.toggle_theme()
        light_bg = await admin_page.get_background_color()

        assert dark_bg != light_bg, f"Background color should differ: dark={dark_bg}, light={light_bg}"

    @pytest.mark.asyncio
    async def test_theme_toggle_button_visible(self, browser_page: Page):
        """Verify theme toggle button is visible on admin page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        assert await admin_page.is_theme_toggle_visible(), "Theme toggle button should be visible"


# =============================================================================
# FORBIDDEN PAGE THEME TESTS
# =============================================================================

class TestForbiddenTheme:
    """Theme tests for the forbidden (403) page."""

    @pytest.mark.asyncio
    async def test_default_theme_is_dark(self, browser_page: Page):
        """Verify that the default theme is dark on forbidden page."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()

        theme = await forbidden_page.get_current_theme()
        assert theme == "dark", f"Expected default theme 'dark', got '{theme}'"

    @pytest.mark.asyncio
    async def test_toggle_button_changes_data_theme_attribute(self, browser_page: Page):
        """Verify clicking theme toggle changes data-theme attribute on forbidden."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()

        await forbidden_page.toggle_theme()

        new_theme = await forbidden_page.get_current_theme()
        assert new_theme == "light", f"Expected 'light' after toggle, got '{new_theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_in_localstorage(self, browser_page: Page):
        """Verify theme choice is saved to localStorage on forbidden page."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()
        await forbidden_page.toggle_theme()

        stored_theme = await forbidden_page.get_stored_theme()
        assert stored_theme == "light", f"Expected 'light' in localStorage, got '{stored_theme}'"

    @pytest.mark.asyncio
    async def test_theme_restored_on_reload(self, browser_page: Page):
        """Verify theme is restored from localStorage on forbidden page reload."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()
        await forbidden_page.toggle_theme()
        assert await forbidden_page.get_current_theme() == "light"

        await browser_page.reload()
        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)

        theme_after_reload = await forbidden_page.get_current_theme()
        assert theme_after_reload == "light", f"Expected 'light' after reload, got '{theme_after_reload}'"

    @pytest.mark.asyncio
    async def test_css_properties_change_with_theme(self, browser_page: Page):
        """Verify CSS properties change when theme is toggled on forbidden."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()

        dark_bg = await forbidden_page.get_background_color()
        await forbidden_page.toggle_theme()
        light_bg = await forbidden_page.get_background_color()

        assert dark_bg != light_bg, f"Background color should differ: dark={dark_bg}, light={light_bg}"

    @pytest.mark.asyncio
    async def test_theme_toggle_button_visible(self, browser_page: Page):
        """Verify theme toggle button is visible on forbidden page."""
        forbidden_page = ForbiddenPage(browser_page, BASE_URL)
        await forbidden_page.navigate()

        assert await forbidden_page.is_theme_toggle_visible(), "Theme toggle button should be visible"


# =============================================================================
# CROSS-PAGE THEME PERSISTENCE TESTS
# =============================================================================

class TestCrossPageThemePersistence:
    """Tests for theme persistence when navigating between pages."""

    @pytest.mark.asyncio
    async def test_theme_persists_login_to_viewer(self, browser_page: Page):
        """Verify theme persists from login page to viewer page after login."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Set light theme on login page
        await login_page.toggle_theme()
        assert await login_page.get_current_theme() == "light"

        # Login and verify theme persists
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        theme = await viewer_page.get_current_theme()
        assert theme == "light", f"Theme should persist from login to viewer, got '{theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_viewer_to_admin(self, browser_page: Page):
        """Verify theme persists from viewer page to admin page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(browser_page, BASE_URL)

        # Set light theme on viewer page
        await viewer_page.toggle_theme()
        assert await viewer_page.get_current_theme() == "light"

        # Navigate to admin
        await viewer_page.click_admin_button()

        admin_page = AdminPage(browser_page, BASE_URL)
        theme = await admin_page.get_current_theme()
        assert theme == "light", f"Theme should persist from viewer to admin, got '{theme}'"

    @pytest.mark.asyncio
    async def test_theme_persists_admin_to_viewer(self, browser_page: Page):
        """Verify theme persists from admin page to viewer page."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        # Set light theme on admin page
        await admin_page.toggle_theme()
        assert await admin_page.get_current_theme() == "light"

        # Navigate to viewer
        await admin_page.click_viewer_button()

        viewer_page = ViewerPage(browser_page, BASE_URL)
        theme = await viewer_page.get_current_theme()
        assert theme == "light", f"Theme should persist from admin to viewer, got '{theme}'"

    @pytest.mark.asyncio
    async def test_theme_survives_logout_login_cycle(self, browser_page: Page):
        """Verify theme persists through logout and login cycle."""
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()

        # Set light theme and login
        await login_page.toggle_theme()
        await login_page.login_as_admin()

        # Logout
        viewer_page = ViewerPage(browser_page, BASE_URL)
        await viewer_page.click_logout_button()

        # Verify theme is still light on login page
        await browser_page.wait_for_timeout(500)
        theme = await login_page.get_current_theme()
        assert theme == "light", f"Theme should survive logout, got '{theme}'"

        # Login again and verify theme persists
        await login_page.login_as_admin()
        theme_after_login = await viewer_page.get_current_theme()
        assert theme_after_login == "light", f"Theme should survive logout/login cycle, got '{theme_after_login}'"
