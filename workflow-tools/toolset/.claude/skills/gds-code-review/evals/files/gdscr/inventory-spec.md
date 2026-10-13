# Story: 2-3 Inventory Stacking

## Status
review

## Acceptance Criteria
- AC1: Adding an item whose id already exists in the inventory MUST merge into the existing stack (increment qty), not create a second slot.
- AC2: `add` MUST reject the addition and return False when the inventory is already at `capacity` and the item is not stackable into an existing slot.
- AC3: `remove` MUST NOT allow a slot's qty to go below zero; removing more than present is an error condition.
- AC4: A slot whose qty reaches zero after a remove MUST be dropped from `slots`.

## Tasks/Subtasks
- [x] Implement add
- [x] Implement remove
