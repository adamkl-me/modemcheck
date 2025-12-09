"""Forbidden page object for Playwright tests."""
from playwright.async_api import Page, expect


class ForbiddenPage:
    """Page object for the 403 forbidden page."""

    URL = "/forbidden"

    def __init__(self, page: Page, base_url: str = "http://localhost:23894"):
        self.page = page
        self.base_url = base_url

        # Locators
        self.error_icon = page.locator(".error-icon")
        self.heading = page.locator("h1")
        self.message = page.locator("p")
        self.return_button = page.locator(".btn")

        # Theme-related locators
        self.theme_toggle = page.locator(".theme-toggle")
        self.theme_icon_light = page.locator(".theme-icon-light")
        self.theme_icon_dark = page.locator(".theme-icon-dark")

    async def navigate(self):
        """Navigate to forbidden page."""
        await self.page.goto(f"{self.base_url}{self.URL}")
        await self.page.wait_for_load_state("domcontentloaded")

    async def is_forbidden_page(self) -> bool:
        """Check if currently on forbidden page."""
        return "/forbidden" in self.page.url

    async def get_heading_text(self) -> str:
        """Get heading text."""
        return await self.heading.text_content() or ""

    async def get_message_text(self) -> str:
        """Get message text."""
        return await self.message.text_content() or ""

    async def click_return_button(self):
        """Click the return to viewer button."""
        await self.return_button.click()
        await self.page.wait_for_load_state("networkidle")

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
        """Get body background color."""
        return await self.page.evaluate(
            "getComputedStyle(document.body).backgroundColor"
        )

    async def get_text_color(self) -> str:
        """Get body text color."""
        return await self.page.evaluate(
            "getComputedStyle(document.body).color"
        )

    async def is_theme_toggle_visible(self) -> bool:
        """Check if theme toggle button is visible."""
        return await self.theme_toggle.is_visible()
