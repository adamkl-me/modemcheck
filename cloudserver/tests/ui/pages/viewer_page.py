"""Viewer page object for Playwright tests."""
from playwright.async_api import Page, expect
from typing import Optional


class ViewerPage:
    """Page object for the data viewer page."""

    URL = "/viewer"

    def __init__(self, page: Page, base_url: str = "http://localhost:23894"):
        self.page = page
        self.base_url = base_url

        # Header buttons
        self.admin_button = page.locator("#adminBtn")
        self.logout_button = page.locator("#logoutBtn")

        # Theme-related locators
        self.theme_toggle = page.locator(".theme-toggle")
        self.theme_icon_light = page.locator(".theme-icon-light")
        self.theme_icon_dark = page.locator(".theme-icon-dark")

        # Filter section
        self.modem_search_input = page.locator("#modemSearchInput")
        self.modem_dropdown = page.locator("#modemDropdown")
        self.start_date_input = page.locator("#startDate")
        self.end_date_input = page.locator("#endDate")
        self.load_button = page.locator("#loadBtn")

        # View toggle (Note: HTML uses "Detail View" not "Single View")
        self.single_view_button = page.locator('.view-btn:has-text("Detail View")')
        self.trend_view_button = page.locator('.view-btn:has-text("Trend View")')

        # Data sections
        self.last_check_section = page.locator("#lastCheckSection")
        self.downstream_table = page.locator("#downstreamTable")
        self.upstream_table = page.locator("#upstreamTable")

    async def navigate(self):
        """Navigate to viewer page."""
        await self.page.goto(f"{self.base_url}{self.URL}")
        await self.page.wait_for_load_state("domcontentloaded")
        # Wait for a key element to be visible instead of networkidle
        await self.load_button.wait_for(state="visible", timeout=10000)

    async def is_viewer_page(self) -> bool:
        """Check if currently on viewer page."""
        return "/viewer" in self.page.url

    async def is_admin_button_visible(self) -> bool:
        """Check if admin button is visible (admin users only)."""
        return await self.admin_button.is_visible()

    async def click_admin_button(self):
        """Click admin button to navigate to admin page."""
        await self.admin_button.click()
        await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_url("**/admin**", timeout=10000)

    async def click_logout_button(self):
        """Click logout button."""
        async with self.page.expect_navigation(timeout=15000):
            await self.logout_button.click()

    async def select_modem(self, modem_id: Optional[str] = None):
        """Select a modem from the dropdown."""
        await self.modem_search_input.click()
        await self.page.wait_for_timeout(500)

        if modem_id:
            await self.modem_search_input.fill(modem_id)
            await self.page.wait_for_timeout(500)

        # Click first option
        first_option = self.modem_dropdown.locator(".searchable-option").first
        if await first_option.is_visible():
            await first_option.click()
            await self.page.wait_for_timeout(500)

    async def load_data(self):
        """Click the load data button."""
        await self.load_button.click()
        await self.page.wait_for_timeout(3000)

    async def switch_to_trend_view(self):
        """Switch to trend view."""
        await self.trend_view_button.click()
        await self.page.wait_for_timeout(500)

    async def switch_to_single_view(self):
        """Switch to single view."""
        await self.single_view_button.click()
        await self.page.wait_for_timeout(500)

    async def is_single_view_active(self) -> bool:
        """Check if single view is active."""
        class_attr = await self.single_view_button.get_attribute("class") or ""
        return "active" in class_attr

    async def is_trend_view_active(self) -> bool:
        """Check if trend view is active."""
        class_attr = await self.trend_view_button.get_attribute("class") or ""
        return "active" in class_attr

    async def get_modem_dropdown_count(self) -> int:
        """Get number of items in modem dropdown."""
        await self.modem_search_input.click()
        await self.page.wait_for_timeout(500)
        items = self.modem_dropdown.locator(".searchable-option")
        return await items.count()

    # Theme methods
    async def get_current_theme(self) -> str:
        """Get current theme from data-theme attribute on html element."""
        return await self.page.evaluate(
            "document.documentElement.getAttribute('data-theme')"
        )

    async def get_stored_theme(self) -> str:
        """Get theme from localStorage."""
        return await self.page.evaluate(
            "localStorage.getItem('modemcheck-theme')"
        )

    async def toggle_theme(self):
        """Click theme toggle button."""
        await self.theme_toggle.click()
        await self.page.wait_for_timeout(300)

    async def set_theme(self, theme: str):
        """Set theme to 'dark' or 'light'."""
        current = await self.get_current_theme()
        if current != theme:
            await self.toggle_theme()

    async def get_background_color(self) -> str:
        """Get theme background color from CSS variable."""
        return await self.page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
        )

    async def get_text_color(self) -> str:
        """Get theme text color from CSS variable."""
        return await self.page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--text').trim()"
        )

    async def is_theme_toggle_visible(self) -> bool:
        """Check if theme toggle button is visible."""
        return await self.theme_toggle.is_visible()
