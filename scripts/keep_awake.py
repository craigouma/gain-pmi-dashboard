import sys

from playwright.sync_api import Page, sync_playwright

APP_URL = "https://gain-pmi-dashboard.streamlit.app/"
READY_TEXT = "Fortified rice seed"
BOOT_ATTEMPTS = 24
BOOT_POLL_MS = 5000


def app_frame(page: Page):
    for frame in page.frames:
        if frame.url.rstrip("/").endswith("/~/+"):
            return frame
    return None


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(6000)

        # A sleeping app serves a wake screen on the top level page, not inside the app's own
        # iframe. A plain HTTP GET reaches this shell and returns 200 without ever starting the
        # Streamlit process, which is why curl based pings report success while the app stays asleep.
        wake_button = page.get_by_role("button", name="get this app back up", exact=False)
        if wake_button.count():
            print("app is asleep, clicking wake button")
            wake_button.first.click()

        for attempt in range(BOOT_ATTEMPTS):
            frame = app_frame(page)
            if frame is not None:
                try:
                    frame.wait_for_selector(f"text={READY_TEXT}", timeout=4000)
                    print(f"app is awake and rendering (attempt {attempt + 1})")
                    browser.close()
                    return 0
                except Exception:
                    pass
            page.wait_for_timeout(BOOT_POLL_MS)

        print("app did not finish booting within the time allowed")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
