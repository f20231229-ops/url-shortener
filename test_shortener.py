"""
Test suite for the URL shortener.
Run with:  python test_shortener.py
"""

import os
import sys
import time
import unittest
import sqlite3

# Bootstrap DB path before importing app
os.environ.setdefault("FLASK_ENV", "testing")
DB_FILE = "test_urls.db"

import app as shortener
shortener.DB_PATH = DB_FILE


def fresh_db():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    shortener.init_db()


class TestIDGeneration(unittest.TestCase):
    """Collision-free ID generation across 10,000+ entries."""

    def setUp(self):
        fresh_db()
        self.client = shortener.app.test_client()

    def tearDown(self):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)

    def test_id_length(self):
        sid = shortener.generate_short_id()
        self.assertEqual(len(sid), shortener.ID_LEN)

    def test_id_charset(self):
        for _ in range(200):
            sid = shortener.generate_short_id()
            self.assertTrue(all(c in shortener.CHARS for c in sid))

    def test_10k_unique_ids(self):
        """Generate 10,000+ IDs and assert zero collisions."""
        N = 10_100
        ids = set()
        with shortener.get_db() as conn:
            for i in range(N):
                sid = shortener.generate_short_id()
                self.assertNotIn(sid, ids, f"Collision at entry {i}: {sid}")
                ids.add(sid)
                conn.execute(
                    "INSERT INTO urls (short_id, long_url, created_at) VALUES (?,?,?)",
                    (sid, f"https://example.com/{i}", "2025-01-01 00:00:00"),
                )
            conn.commit()
        self.assertEqual(len(ids), N)
        print(f"\n  ✓ Generated {N:,} unique IDs with zero collisions")


class TestRoutes(unittest.TestCase):

    def setUp(self):
        fresh_db()
        shortener.app.config["TESTING"] = True
        self.client = shortener.app.test_client()

    def tearDown(self):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)

    def test_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_shorten_valid(self):
        r = self.client.post("/shorten",
                             json={"url": "https://example.com"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("short_url", data)
        self.assertIn("short_id", data)
        self.assertEqual(len(data["short_id"]), shortener.ID_LEN)

    def test_shorten_prepends_https(self):
        r = self.client.post("/shorten",
                             json={"url": "example.com"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        # Verify the long URL stored includes https://
        stats = self.client.get(f"/stats/{data['short_id']}").get_json()
        self.assertTrue(stats["long_url"].startswith("https://"))

    def test_shorten_empty(self):
        r = self.client.post("/shorten",
                             json={"url": ""},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_redirect_and_click_tracking(self):
        # create link
        r  = self.client.post("/shorten", json={"url": "https://openai.com"})
        sid = r.get_json()["short_id"]

        # check zero clicks
        stats = self.client.get(f"/stats/{sid}").get_json()
        self.assertEqual(stats["clicks"], 0)

        # redirect once
        r2 = self.client.get(f"/{sid}")
        self.assertEqual(r2.status_code, 302)

        # check one click
        stats2 = self.client.get(f"/stats/{sid}").get_json()
        self.assertEqual(stats2["clicks"], 1)

    def test_sub_100ms_redirect(self):
        r   = self.client.post("/shorten", json={"url": "https://python.org"})
        sid = r.get_json()["short_id"]

        t0 = time.perf_counter()
        self.client.get(f"/{sid}")
        elapsed = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed, 100, f"Redirect took {elapsed:.1f} ms (> 100 ms)")
        print(f"\n  ✓ Redirect latency: {elapsed:.2f} ms")

    def test_404_on_missing(self):
        r = self.client.get("/xxxxxx")
        self.assertEqual(r.status_code, 404)

    def test_recent_api(self):
        for i in range(3):
            self.client.post("/shorten", json={"url": f"https://example{i}.com"})
        r = self.client.get("/api/recent")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
