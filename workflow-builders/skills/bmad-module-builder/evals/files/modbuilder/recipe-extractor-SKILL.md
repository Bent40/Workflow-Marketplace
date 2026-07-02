---
name: recipe-extractor
description: Extracts structured recipes from messy web pages and also validates an existing recipe file against the schema. Use when the user wants to pull a recipe out of a page or check a recipe file.
---

# Recipe Extractor

## Overview

This skill has two distinct modes:

- **Extract** — given a URL or pasted HTML of a recipe blog post, pull out the title, ingredient list (with quantities and units), and ordered steps, and emit a clean structured `recipe.json`.
- **Validate** — given an existing `recipe.json`, check it against the recipe schema (required fields present, quantities numeric, steps non-empty) and report any violations.

## Extract

Parse the page, strip the life-story preamble, and produce structured JSON.

## Validate

Walk the schema and report missing or malformed fields.
