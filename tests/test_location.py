import unittest

from job_tools.location import greenhouse_matches_location, normalize_search_location


class LocationTests(unittest.TestCase):
    def test_search_choices(self):
        self.assertEqual(normalize_search_location("NYC"), "nyc")
        self.assertEqual(normalize_search_location("New York"), "nyc")
        self.assertEqual(normalize_search_location("Remote"), "remote")
        with self.assertRaisesRegex(ValueError, "nyc.*remote"):
            normalize_search_location("Boston")

    def test_nyc_matches_explicit_city_labels(self):
        for label in ("NYC", "New York City", "New York, NY", "Brooklyn, NY",
                      "San Francisco, CA • New York, NY • United States"):
            with self.subTest(label=label):
                self.assertTrue(greenhouse_matches_location({"location": {"name": label}}, "nyc"))
        for label in ("New York State", "York, PA", "US-Remote", ""):
            with self.subTest(label=label):
                self.assertFalse(greenhouse_matches_location({"location": {"name": label}}, "nyc"))

    def test_remote_accepts_explicit_us_or_nyc_labels_only(self):
        for label in ("Remote", "US-Remote", "Remote - USA", "Remote in the US",
                      "Remote, USA", "Remote - New York, NY"):
            with self.subTest(label=label):
                self.assertTrue(greenhouse_matches_location({"location": {"name": label}}, "remote"))
        for label in ("Remote - Bengaluru, India", "Poland - Remote OR Romania - Remote",
                      "Dublin or Germany (Berlin or Remote)", "Remote - Canada", "New York, NY", ""):
            with self.subTest(label=label):
                self.assertFalse(greenhouse_matches_location({"location": {"name": label}}, "remote"))


if __name__ == "__main__":
    unittest.main()
