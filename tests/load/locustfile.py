"""Locust load test scenarios for browser-use."""

from locust import HttpUser, between, task


class BrowserUseUser(HttpUser):
    """Simulated user hitting the browser-use extraction API."""

    wait_time = between(1, 3)

    @task(60)
    def extract_simple(self):
        """Baseline — extract example.com (fast)."""
        self.client.post(
            "/extract",
            json={"url": "https://example.com/"},
        )

    @task(30)
    def extract_wikipedia(self):
        """Medium — extract a Wikipedia page."""
        self.client.post(
            "/extract",
            json={"url": "https://en.wikipedia.org/wiki/Web_scraping"},
        )

    @task(10)
    def extract_pdf(self):
        """Heavy — extract an arxiv PDF."""
        self.client.post(
            "/extract",
            json={"url": "https://arxiv.org/pdf/1706.03762.pdf"},
        )

    @task(5)
    def healthcheck(self):
        """Quick health check."""
        self.client.get("/healthz")
