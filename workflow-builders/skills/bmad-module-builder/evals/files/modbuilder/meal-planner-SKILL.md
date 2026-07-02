---
name: meal-planner
description: Builds a weekly meal plan from a set of extracted recipes, balancing nutrition and minimizing grocery waste. Use when the user wants to plan a week of meals.
---

# Meal Planner

## Overview

Given a collection of structured recipes, assemble a 7-day meal plan that balances macros across the week and reuses overlapping ingredients to cut down on grocery waste. Output a `meal-plan.md` with a day-by-day schedule and a consolidated shopping list.

## Process

Score recipes for nutritional balance, cluster by shared ingredients, and lay out the week.
