import io
import json
import unittest
from unittest.mock import patch
import urllib.error

import recipes


def sample_recipes():
    return {
        "recipes": [
            {
                "title": f"Recipe {number}",
                "ingredients": [
                    {"name": "1 cup rice", "in_fridge": True},
                    {"name": "2 tbsp oil", "in_fridge": False},
                ],
                "instructions": ["Cook the rice.", "Serve warm."],
                "cook_time_minutes": 20,
            }
            for number in range(1, 4)
        ]
    }


def api_response(payload):
    return io.BytesIO(json.dumps({
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }).encode("utf-8"))


class RecipeTests(unittest.TestCase):
    def test_prompt_includes_only_provided_constraints(self):
        prompt = recipes.build_prompt(["rice", "beans"], ["vegan"], None, 30, None)
        self.assertIn('"max_cook_time_minutes": 30', prompt)
        self.assertIn('"vegan"', prompt)
        self.assertNotIn('"cuisine"', prompt)
        self.assertNotIn('"servings"', prompt)

    def test_validates_exactly_three_recipes(self):
        self.assertEqual(len(recipes.validate_recipes(sample_recipes())), 3)
        with self.assertRaisesRegex(recipes.RecipeError, "exactly three"):
            recipes.validate_recipes({"recipes": sample_recipes()["recipes"][:2]})

    def test_rejects_recipes_over_requested_time_limit(self):
        with self.assertRaisesRegex(recipes.RecipeError, "exceeds the requested maximum"):
            recipes.validate_recipes(sample_recipes(), max_cook_time=15)

    def test_formats_fridge_status_and_instructions(self):
        output = recipes.format_recipes(recipes.validate_recipes(sample_recipes()))
        self.assertIn("[IN FRIDGE] 1 cup rice", output)
        self.assertIn("[MISSING] 2 tbsp oil", output)
        self.assertIn("1. Cook the rice.", output)
        self.assertIn("Estimated cook time: 20 minutes", output)

    @patch("recipes.time.sleep")
    @patch("recipes.urllib.request.urlopen")
    def test_retries_transient_http_error(self, mock_urlopen, mock_sleep):
        transient_error = urllib.error.HTTPError(
            f"{recipes.API_URL}/{recipes.DEFAULT_MODEL}:generateContent",
            503,
            "unavailable",
            {},
            io.BytesIO(b"service down"),
        )
        mock_urlopen.side_effect = [transient_error, api_response(sample_recipes())]

        result = recipes.request_recipes("test-key", "prompt")

        self.assertEqual(len(result), 3)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(1)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            f"{recipes.API_URL}/{recipes.DEFAULT_MODEL}:generateContent",
        )
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(
            json.loads(request.data)["generationConfig"]["responseMimeType"],
            "application/json",
        )

    @patch("recipes.urllib.request.urlopen")
    def test_does_not_retry_permanent_http_error(self, mock_urlopen):
        error = urllib.error.HTTPError(
            f"{recipes.API_URL}/{recipes.DEFAULT_MODEL}:generateContent",
            401,
            "unauthorized",
            {},
            io.BytesIO(b"bad key"),
        )
        mock_urlopen.side_effect = error
        with self.assertRaisesRegex(recipes.RecipeError, "HTTP 401"):
            recipes.request_recipes("test-key", "prompt")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertTrue(error.fp.closed)


if __name__ == "__main__":
    unittest.main()
