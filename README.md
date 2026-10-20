# Fridge-to-Recipes

A local website that suggests three recipes from ingredients you have on hand. Each suggestion includes a full ingredient list labeled **IN FRIDGE** or **MISSING**, step-by-step instructions, and estimated cook time. Your Gemini API key stays in the local Python server and is never sent to the browser.

## Requirements

- Python 3.10 or newer
- A Google AI Studio Gemini API key

## Setup

Create a Gemini API key in Google AI Studio, then set it in the environment; do not put it in source code:

```powershell
$env:GEMINI_API_KEY = "your-google-ai-key"
```

Optionally set `GEMINI_MODEL` to choose a Gemini model. The default is `gemini-3.8-flash`.

## Run the local website

Set the key in PowerShell, then start the website:

```powershell
$env:GEMINI_API_KEY = "your-google-ai-key"
python webapp.py
```

The app opens in your browser at `http://127.0.0.1:8000`. Keep the terminal running while using it; press `Ctrl+C` there to stop the server. The website only listens on your computer. Optionally set `GEMINI_MODEL` before starting to choose a model; the default is `gemini-3.8-flash`.

Enter ingredients separated by commas or new lines. Dietary restrictions, cuisine, maximum cook time, and servings are optional.

## Example run

Start the site:

```powershell
python webapp.py
```

In the browser, enter `cooked rice, eggs, spinach`, choose `vegetarian` and `Japanese`, set max cook time to `30` minutes and servings to `2`, then select **Find my recipes**. Example recipe card output (suggestions vary):

```text
Japanese Spinach and Egg Rice Bowl · About 20 minutes

Ingredients
- 2 cups cooked rice — IN FRIDGE
- 2 eggs — IN FRIDGE
- 1 cup spinach — IN FRIDGE
- 1 tbsp soy sauce — MISSING

Instructions
1. Warm the rice and wilt the spinach in a pan.
2. Scramble the eggs, then serve over the rice with soy sauce.

Two more recipe cards are shown in the browser.
```

The website retries transient Gemini/network errors up to three times and displays actionable errors for missing keys, API failures, and invalid responses.

## CLI (optional)

The original command-line interface is still available:

```powershell
python recipes.py --ingredients "cooked rice, eggs, spinach" --dietary vegetarian --cuisine Japanese --max-cook-time 30 --servings 2
```

## Tests

Run the standard-library test suite with:

```powershell
python -m unittest
```
