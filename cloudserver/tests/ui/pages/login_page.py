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

    async def navigate(self):
        """Navigate to login page."""
        await self.page.goto(f"{self.base_url}{self.URL}")
        await self.page.wait_for_load_state("domcontentloaded")
        await self.page.wait_for_timeout(500)

    async def login(self, username: str, password: str):
        """Perform login with given credentials."""
        await self.username_input.fill(username)
        await self.password_input.fill(password)
        await self.login_button.click()
        await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        await self.page.wait_for_timeout(1000)

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
