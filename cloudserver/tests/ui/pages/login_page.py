"""Login page object for Playwright tests."""
from playwright.async_api import Page, expect


class LoginPage:
    """Page object for the login page."""

    URL = "/login"

    def __init__(self, page: Page, base_url: str = "http://localhost:23894"):
        self.page = page
        self.base_url = base_url

        # Locators
        self.username_input = page.locator("#username")
        self.password_input = page.locator("#password")
        self.login_button = page.locator('button[type="submit"]')
        self.error_message = page.locator("#error")
        self.logo = page.locator(".logo h1")

        # Theme-related locators
        self.theme_toggle = page.locator(".theme-toggle")
        self.theme_icon_light = page.locator(".theme-icon-light")
        self.theme_icon_dark = page.locator(".theme-icon-dark")

    async def navigate(self):
        """Navigate to login page."""
        await self.page.goto(f"{self.base_url}{self.URL}")
        await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_timeout(500)

    async def login(self, username: str, password: str, expect_success: bool = True):
        """Perform login with given credentials.

        Args:
            username: Username to login with
            password: Password to login with
            expect_success: If True, waits for redirect to viewer page
        """
        await self.username_input.fill(username)
        await self.password_input.fill(password)
        await self.login_button.click()

        if expect_success:
            # Wait for redirect to viewer page (handles slow browsers like WebKit)
            try:
                await self.page.wait_for_url("**/viewer**", timeout=10000)
            except Exception:
                # If timeout, still wait for page to settle
                await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        else:
            # For failed logins, just wait for page to settle
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            await self.page.wait_for_timeout(500)

    async def login_as_admin(self):
        """Login as admin user."""
        await self.login("admin", "TestPass123!")

    async def login_as_basic(self):
        """Login as basic user."""
        await self.login("test_basic", "BasicPass123!")

    async def login_as_elevated(self):
        """Login as elevated user."""
        await self.login("test_elevated", "ElevatedPass123!")

    async def is_login_page(self) -> bool:
        """Check if currently on login page."""
        return "/login" in self.page.url

    async def get_error_message(self) -> str:
        """Get error message text."""
        if await self.error_message.is_visible():
            return await self.error_message.text_content()
        return ""

    async def is_error_visible(self) -> bool:
        """Check if error message is visible."""
        return await self.error_message.is_visible()

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
        """Get theme background color from CSS variable.

        Note: body.backgroundColor is transparent because background uses a gradient.
        We check the --bg CSS variable which is different between light/dark themes.
        """
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
