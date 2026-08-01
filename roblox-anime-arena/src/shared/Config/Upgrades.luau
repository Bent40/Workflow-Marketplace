--!strict
--[[
	Upgrades.luau

	The four permanent gold sinks from the reference's UPGRADES panel. Each is a
	geometric cost curve with a linear or geometric effect curve.
]]

export type UpgradeId = "Gold" | "Slot" | "Luck" | "Inventory"

export type Upgrade = {
	Id: UpgradeId,
	Display: string,
	Description: string,
	MaxLevel: number,
	BaseCost: number,
	CostGrowth: number,
	-- Effect at level L is EffectBase + (L - 1) * EffectStep.
	EffectBase: number,
	EffectStep: number,
	-- Formatting hint for the UI.
	Format: "multiplier" | "count",
	Icon: string,
}

local Upgrades = {}

Upgrades.Order = { "Gold", "Luck", "Slot", "Inventory" } :: { UpgradeId }

Upgrades.Data = {
	Gold = {
		Id = "Gold",
		Display = "Gold Upgrade",
		Description = "Increase the amount of gold you get from killing enemies.",
		MaxLevel = 40,
		BaseCost = 5000,
		CostGrowth = 1.55,
		EffectBase = 1.0,
		EffectStep = 0.10,
		Format = "multiplier",
		Icon = "💰",
	},
	Luck = {
		Id = "Luck",
		Display = "Luck Upgrade",
		Description = "Increase the chance of rolling rarer animes.",
		MaxLevel = 40,
		BaseCost = 7500,
		CostGrowth = 1.62,
		EffectBase = 1.0,
		EffectStep = 0.50,
		Format = "multiplier",
		Icon = "🍀",
	},
	Slot = {
		Id = "Slot",
		Display = "Slot Upgrade",
		Description = "Unlock more slots to place more animes.",
		MaxLevel = 15,
		BaseCost = 25000,
		CostGrowth = 2.05,
		EffectBase = 5,
		EffectStep = 1,
		Format = "count",
		Icon = "🧩",
	},
	Inventory = {
		Id = "Inventory",
		Display = "Inventory Upgrade",
		Description = "Increase inventory capacity to store more animes.",
		MaxLevel = 20,
		BaseCost = 15000,
		CostGrowth = 1.70,
		EffectBase = 125,
		EffectStep = 25,
		Format = "count",
		Icon = "🎒",
	},
} :: { [UpgradeId]: Upgrade }

function Upgrades.get(id: UpgradeId): Upgrade
	local up = Upgrades.Data[id]
	assert(up, `Upgrades.get: unknown upgrade "{tostring(id)}"`)
	return up
end

-- Cost to go from `level` to `level + 1`. Returns nil at max level.
function Upgrades.costToNext(id: UpgradeId, level: number): number?
	local up = Upgrades.get(id)
	if level >= up.MaxLevel then
		return nil
	end
	return math.floor(up.BaseCost * up.CostGrowth ^ (level - 1) + 0.5)
end

function Upgrades.effectAt(id: UpgradeId, level: number): number
	local up = Upgrades.get(id)
	local clamped = math.clamp(level, 1, up.MaxLevel)
	local value = up.EffectBase + (clamped - 1) * up.EffectStep
	if up.Format == "count" then
		return math.floor(value + 0.5)
	end
	return value
end

function Upgrades.formatEffect(id: UpgradeId, level: number): string
	local up = Upgrades.get(id)
	local value = Upgrades.effectAt(id, level)
	if up.Format == "multiplier" then
		return `x{string.format("%.1f", value)}`
	end
	return tostring(value)
end

return Upgrades
