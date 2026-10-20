import json
import io
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import webapp


SAMPLE_RECIPES = [
    {
        "title": f"Test recipe {number}",
        "ingredients": [
            {"name": "1 cup rice", "in_fridge": True},
            {"name": "1 tbsp oil", "in_fridge": False},
        ],
        "instructions": ["Cook the rice."],
        "cook_time_minutes": 20,
    }
    for number in range(1, 4)
]


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.RecipeRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, payload, content_type="application/json"):
        request = urllib.request.Request(
            f"{self.base_url}/api/recipes",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            return error

    def test_homepage_serves_local_form(self):
        with urllib.request.urlopen(f"{self.base_url}/") as response:
            page = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('id="recipe-form"', page)
        self.assertIn("/api/recipes", page)

    def test_favicon_request_is_handled_without_not_found(self):
        with urllib.request.urlopen(f"{self.base_url}/favicon.ico") as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b"")

    def test_recipe_endpoint_calls_gemini_client_and_returns_recipes(self):
        payload = {
            "ingredients": ["rice", "eggs"],
            "dietary": ["vegetarian"],
            "cuisine": "Japanese",
            "max_cook_time": 30,
            "servings": 2,
        }
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("webapp.recipes.request_recipes", return_value=SAMPLE_RECIPES) as call:
                with self.post(payload) as response:
                    result = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(result["recipes"], SAMPLE_RECIPES)
        args = call.call_args.args
        self.assertEqual(args[0], "test-key")
        self.assertIn('"Japanese"', args[1])
        self.assertEqual(args[3], 30)

    def test_invalid_payload_returns_client_error(self):
        with self.post({"ingredients": [], "dietary": []}) as response:
            self.assertEqual(response.status, 400)
            self.assertIn("Add at least one ingredient", json.loads(response.read())["error"])

    def test_missing_key_returns_actionable_error(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.post({"ingredients": ["rice"]}) as response:
                self.assertEqual(response.status, 503)
                self.assertIn("GEMINI_API_KEY", json.loads(response.read())["error"])

    def test_upstream_error_is_reported_in_server_terminal(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch(
                "webapp.recipes.request_recipes",
                side_effect=webapp.recipes.RecipeError("model unavailable"),
            ):
                error_output = io.StringIO()
                with redirect_stderr(error_output):
                    with self.post({"ingredients": ["rice"]}) as response:
                        self.assertEqual(response.status, 502)
                        self.assertIn("model unavailable", json.loads(response.read())["error"])
        self.assertIn("Recipe request failed: model unavailable", error_output.getvalue())

    def test_rejects_non_json_content_type(self):
        with self.post({"ingredients": ["rice"]}, "text/plain") as response:
            self.assertEqual(response.status, 415)


if __name__ == "__main__":
    unittest.main()
