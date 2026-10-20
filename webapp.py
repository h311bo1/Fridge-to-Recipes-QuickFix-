"""Serve the local recipe website and its Gemini-backed API."""

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import recipes


HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_REQUEST_BYTES = 16_384
INDEX_PATH = Path(__file__).with_name("index.html")


def parse_recipe_request(payload: Any) -> tuple[list[str], list[str], str | None, int | None, int | None]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    ingredients = payload.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise ValueError("Add at least one ingredient.")
    if any(not isinstance(item, str) for item in ingredients):
        raise ValueError("Ingredients must be text.")
    ingredients = [item.strip() for item in ingredients if item.strip()]
    if not ingredients:
        raise ValueError("Add at least one ingredient.")
    if len(ingredients) > 100 or any(len(item) > 120 for item in ingredients):
        raise ValueError("Use no more than 100 ingredients, with up to 120 characters each.")

    dietary = payload.get("dietary", [])
    if not isinstance(dietary, list) or any(not isinstance(item, str) for item in dietary):
        raise ValueError("Dietary restrictions must be a list of text values.")
    dietary = [item.strip() for item in dietary if item.strip()]
    if len(dietary) > 20:
        raise ValueError("Use no more than 20 dietary restrictions.")

    cuisine = payload.get("cuisine", "")
    if not isinstance(cuisine, str):
        raise ValueError("Cuisine must be text.")
    cuisine = cuisine.strip() or None
    if cuisine and len(cuisine) > 100:
        raise ValueError("Cuisine must be 100 characters or fewer.")

    max_cook_time = _optional_positive_int(payload.get("max_cook_time"), "Maximum cook time")
    servings = _optional_positive_int(payload.get("servings"), "Servings")
    return ingredients, dietary, cuisine, max_cook_time, servings


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive whole number.")
    if value > 10000:
        raise ValueError(f"{label} is too large.")
    return value


class RecipeRequestHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path != "/":
            self._send_json(404, {"error": "Not found."})
            return
        try:
            page = INDEX_PATH.read_bytes()
        except OSError as exc:
            self._send_json(500, {"error": f"Could not load the website: {exc}"})
            return
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/recipes":
            self._send_json(404, {"error": "Not found."})
            return

        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._send_json(415, {"error": "Send the request as application/json."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "A valid Content-Length is required."})
            return
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body is empty or too large."})
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            ingredients, dietary, cuisine, max_cook_time, servings = parse_recipe_request(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"error": str(exc) or "Invalid JSON request."})
            return

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self._send_json(
                503,
                {"error": "Set the GEMINI_API_KEY environment variable, then restart the website."},
            )
            return

        prompt = recipes.build_prompt(ingredients, dietary, cuisine, max_cook_time, servings)
        try:
            suggestions = recipes.request_recipes(
                api_key,
                prompt,
                os.environ.get("GEMINI_MODEL", recipes.DEFAULT_MODEL),
                max_cook_time,
            )
        except recipes.RecipeError as exc:
            print(f"Recipe request failed: {exc}", file=sys.stderr)
            self._send_json(502, {"error": str(exc)})
            return
        self._send_json(200, {"recipes": suggestions})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} - {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, DEFAULT_PORT), RecipeRequestHandler)
    url = f"http://{HOST}:{server.server_port}/"
    print(f"Recipe website running at {url}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping recipe website.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
