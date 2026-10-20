"""Suggest recipes from ingredients on hand using the Google Gemini API."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_ATTEMPTS = 3


class RecipeError(Exception):
    """An expected error while requesting or parsing recipe suggestions."""


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_prompt(
    ingredients: list[str],
    dietary: list[str],
    cuisine: str | None,
    max_cook_time: int | None,
    servings: int | None,
) -> str:
    constraints: dict[str, Any] = {}
    if dietary:
        constraints["dietary_restrictions"] = dietary
    if cuisine:
        constraints["cuisine"] = cuisine
    if max_cook_time is not None:
        constraints["max_cook_time_minutes"] = max_cook_time
    if servings is not None:
        constraints["servings"] = servings

    return (
        "Suggest exactly three distinct, practical recipes using the user's "
        "ingredients and respecting every supplied constraint. You may include "
        "additional ingredients, but accurately mark whether each ingredient "
        "is already on hand. Return only a JSON object with this shape: "
        '{"recipes":[{"title":"...","ingredients":['
        '{"name":"full ingredient and quantity","in_fridge":true}],'
        '"instructions":["..."],"cook_time_minutes":30}]}. '
        "Include all ingredients and clear, ordered cooking instructions. "
        "Use a positive integer for cook_time_minutes. For each ingredient, "
        "set in_fridge true only when the user's list includes it; otherwise "
        "set it false. Do not exceed the cook-time limit. "
        f"Ingredients on hand: {json.dumps(ingredients)}. "
        f"Constraints: {json.dumps(constraints)}."
    )


def _read_response(response: Any) -> dict[str, Any]:
    try:
        data = json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecipeError("The recipe service returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RecipeError("The recipe service returned an unexpected response.")
    return data


def request_recipes(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_cook_time: int | None = None,
) -> list[dict[str, Any]]:
    body = json.dumps(
        {
            "systemInstruction": {
                "parts": [
                    {
                        "text": "You are a careful recipe assistant. Follow the requested JSON format."
                    }
                ]
            },
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/{urllib.parse.quote(model, safe='-')}:generateContent",
        data=body,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = _read_response(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429) and not 500 <= exc.code <= 599:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                finally:
                    exc.close()
                raise RecipeError(
                    f"Recipe service returned HTTP {exc.code}: {detail}"
                ) from exc
            exc.close()
            if attempt == MAX_ATTEMPTS - 1:
                raise RecipeError(
                    f"Recipe service is temporarily unavailable (HTTP {exc.code}) "
                    f"after {MAX_ATTEMPTS} attempts."
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise RecipeError(
                    f"Could not reach the recipe service after {MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(2**attempt)

    try:
        parts = data["candidates"][0]["content"]["parts"]
        content = "".join(part["text"] for part in parts if "text" in part)
        if not content:
            raise KeyError("text")
        result = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RecipeError("The recipe service response did not contain recipe JSON.") from exc

    return validate_recipes(result, max_cook_time)


def validate_recipes(
    result: Any,
    max_cook_time: int | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("recipes"), list):
        raise RecipeError("The recipe response must contain a recipes list.")
    recipes = result["recipes"]
    if len(recipes) != 3:
        raise RecipeError("The recipe service must return exactly three recipes.")

    for index, recipe in enumerate(recipes, start=1):
        if not isinstance(recipe, dict):
            raise RecipeError(f"Recipe {index} is not a JSON object.")
        if not isinstance(recipe.get("title"), str) or not recipe["title"].strip():
            raise RecipeError(f"Recipe {index} has no title.")
        if not isinstance(recipe.get("ingredients"), list) or not recipe["ingredients"]:
            raise RecipeError(f"Recipe {index} must include its ingredients.")
        for ingredient in recipe["ingredients"]:
            if (
                not isinstance(ingredient, dict)
                or not isinstance(ingredient.get("name"), str)
                or not ingredient["name"].strip()
                or not isinstance(ingredient.get("in_fridge"), bool)
            ):
                raise RecipeError(
                    f"Recipe {index} has an ingredient without a name and fridge status."
                )
        if not isinstance(recipe.get("instructions"), list) or not recipe["instructions"]:
            raise RecipeError(f"Recipe {index} must include cooking instructions.")
        if any(not isinstance(step, str) or not step.strip() for step in recipe["instructions"]):
            raise RecipeError(f"Recipe {index} has an invalid instruction.")
        cook_time = recipe.get("cook_time_minutes")
        if isinstance(cook_time, bool) or not isinstance(cook_time, int) or cook_time < 1:
            raise RecipeError(f"Recipe {index} must have a positive cook time in minutes.")
        if max_cook_time is not None and cook_time > max_cook_time:
            raise RecipeError(
                f"Recipe {index} exceeds the requested maximum cook time "
                f"of {max_cook_time} minutes."
            )
    return recipes


def format_recipes(recipes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for number, recipe in enumerate(recipes, start=1):
        lines.extend(
            [
                f"{number}. {recipe['title']}",
                f"   Estimated cook time: {recipe['cook_time_minutes']} minutes",
                "   Ingredients:",
            ]
        )
        for ingredient in recipe["ingredients"]:
            status = "IN FRIDGE" if ingredient["in_fridge"] else "MISSING"
            lines.append(f"     - [{status}] {ingredient['name']}")
        lines.append("   Instructions:")
        for step_number, step in enumerate(recipe["instructions"], start=1):
            lines.append(f"     {step_number}. {step}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Get three recipes from ingredients you have on hand."
    )
    parser.add_argument(
        "--ingredients",
        required=True,
        help='Comma-separated ingredients, for example "eggs, spinach, rice"',
    )
    parser.add_argument(
        "--dietary",
        action="append",
        default=[],
        help="Dietary restriction (repeat this option for multiple restrictions)",
    )
    parser.add_argument("--cuisine", help="Cuisine preference, such as Thai or Italian")
    parser.add_argument(
        "--max-cook-time",
        type=positive_int,
        help="Maximum estimated cook time in minutes",
    )
    parser.add_argument("--servings", type=positive_int, help="Number of servings")
    args = parser.parse_args(argv)

    ingredients = [item.strip() for item in args.ingredients.split(",") if item.strip()]
    if not ingredients:
        parser.error("provide at least one ingredient")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: set the GEMINI_API_KEY environment variable.", file=sys.stderr)
        return 1

    prompt = build_prompt(
        ingredients,
        args.dietary,
        args.cuisine,
        args.max_cook_time,
        args.servings,
    )
    try:
        recipes = request_recipes(
            api_key,
            prompt,
            os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
            args.max_cook_time,
        )
    except RecipeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(format_recipes(recipes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
