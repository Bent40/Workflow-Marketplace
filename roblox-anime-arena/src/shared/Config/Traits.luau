--!strict
--[[
	Traits.luau

	Traits are a second roll layered on top of the unit roll. Every summoned unit
	gets one (possibly `None`), and it can be rerolled at the Trait Machine using
	Trait Shards.

	All modifiers are expressed as multipliers on the unit's base stats so the
	stat pipeline in StatMath stays a single flat multiply.
]]

local Rarities = require(script.Parent.Rarities)

export type TraitId = string

export type TraitMods = {
	Damage: number?,
	Health: number?,
	-- Attack speed: >1 means faster (shorter cooldown).
	AttackSpeed: number?,
	CritChance: number?, -- additive, in percentage points (0.10 = +10pp)
	CritDamage: number?, -- additive, in percentage points
	Cash: number?,
	Range: number?,
	-- Number of physical unit instances spawned per placement.
	Summons: number?,
}

export type Trait = {
	Id: TraitId,
	Display: string,
	Rarity: Rarities.RarityId,
	Weight: number,
	Mods: TraitMods,
}

local Traits = {}

--[[
	Weights are relative within the whole trait pool (including `None`), so the
	practical odds of a God trait land near 0.02% at base luck — deliberately in
	the same ballpark as the reference game's trait machine.
]]
Traits.Data = {
	None = {
		Id = "None",
		Display = "None",
		Rarity = "Common",
		Weight = 5200,
		Mods = {},
	},

	-- Rare
	Sharp = {
		Id = "Sharp",
		Display = "Sharp",
		Rarity = "Rare",
		Weight = 1400,
		Mods = { CritChance = 0.10, CritDamage = 0.25 },
	},
	Swift = {
		Id = "Swift",
		Display = "Swift",
		Rarity = "Rare",
		Weight = 1400,
		Mods = { AttackSpeed = 1.10 },
	},
	Strong = {
		Id = "Strong",
		Display = "Strong",
		Rarity = "Rare",
		Weight = 1400,
		Mods = { Damage = 1.10 },
	},

	-- Epic
	Deadly = {
		Id = "Deadly",
		Display = "Deadly",
		Rarity = "Epic",
		Weight = 340,
		Mods = { CritChance = 0.15, CritDamage = 0.30 },
	},
	Rush = {
		Id = "Rush",
		Display = "Rush",
		Rarity = "Epic",
		Weight = 340,
		Mods = { AttackSpeed = 1.15 },
	},
	Powerful = {
		Id = "Powerful",
		Display = "Powerful",
		Rarity = "Epic",
		Weight = 340,
		Mods = { Damage = 1.20, Health = 1.10 },
	},

	-- Legendary
	Deadeye = {
		Id = "Deadeye",
		Display = "Deadeye",
		Rarity = "Legendary",
		Weight = 46,
		Mods = { CritChance = 0.35, CritDamage = 0.45 },
	},
	Juggernaut = {
		Id = "Juggernaut",
		Display = "Juggernaut",
		Rarity = "Legendary",
		Weight = 46,
		Mods = { Damage = 1.50, Health = 1.35, AttackSpeed = 0.90 },
	},
	Lethal = {
		Id = "Lethal",
		Display = "Lethal",
		Rarity = "Legendary",
		Weight = 34,
		Mods = { Damage = 1.35, CritChance = 0.30, CritDamage = 0.40 },
	},
	Royal = {
		Id = "Royal",
		Display = "Royal",
		Rarity = "Legendary",
		Weight = 34,
		Mods = { Damage = 1.25, Health = 1.15, Cash = 1.25 },
	},

	-- Mythic
	Entrepreneur = {
		Id = "Entrepreneur",
		Display = "Entrepreneur",
		Rarity = "Mythic",
		Weight = 5.0,
		Mods = { Damage = 1.45, Health = 1.25, AttackSpeed = 1.10, Cash = 1.65 },
	},
	Reaper = {
		Id = "Reaper",
		Display = "Reaper",
		Rarity = "Mythic",
		Weight = 3.4,
		Mods = {
			Damage = 1.90,
			Health = 1.35,
			AttackSpeed = 1.16,
			CritChance = 0.35,
			CritDamage = 0.45,
		},
	},
	Cloner = {
		Id = "Cloner",
		Display = "Cloner",
		Rarity = "Mythic",
		Weight = 2.2,
		Mods = { Damage = 1.40, Health = 1.60, Summons = 2 },
	},
	Superior = {
		Id = "Superior",
		Display = "Superior",
		Rarity = "Mythic",
		Weight = 1.1,
		Mods = {
			Damage = 3.00,
			Health = 2.00,
			AttackSpeed = 1.20,
			CritChance = 0.40,
			CritDamage = 0.65,
		},
	},

	-- God
	Cursed = {
		Id = "Cursed",
		Display = "Cursed",
		Rarity = "God",
		Weight = 0.26,
		Mods = {
			Damage = 5.00,
			Health = 3.00,
			AttackSpeed = 1.25,
			Cash = 1.65,
			CritChance = 0.50,
			CritDamage = 1.00,
		},
	},
	-- Our own top-end trait: the reference tops out at one God trait, so we add a
	-- second chase target that rewards board width instead of raw single-unit power.
	Ascendant = {
		Id = "Ascendant",
		Display = "Ascendant",
		Rarity = "God",
		Weight = 0.12,
		Mods = {
			Damage = 3.50,
			Health = 2.50,
			AttackSpeed = 1.20,
			Range = 1.45,
			Cash = 1.40,
			Summons = 2,
			CritChance = 0.35,
			CritDamage = 0.80,
		},
	},
} :: { [TraitId]: Trait }

Traits.RerollCost = 1 -- Trait Shards per reroll

function Traits.get(id: TraitId?): Trait
	if id == nil then
		return Traits.Data.None
	end
	return Traits.Data[id] or Traits.Data.None
end

-- Ordered id list, weakest tier first, for index/collection UIs.
function Traits.ordered(): { TraitId }
	local ids: { TraitId } = {}
	for id in Traits.Data do
		table.insert(ids, id)
	end
	table.sort(ids, function(a, b)
		local ra, rb = Traits.Data[a], Traits.Data[b]
		local oa, ob = Rarities.get(ra.Rarity).Order, Rarities.get(rb.Rarity).Order
		if oa ~= ob then
			return oa < ob
		end
		return ra.Weight > rb.Weight
	end)
	return ids
end

-- Total weight of the pool, cached on first use.
local totalWeight: number? = nil
function Traits.totalWeight(): number
	if totalWeight then
		return totalWeight
	end
	local sum = 0
	for _, trait in Traits.Data do
		sum += trait.Weight
	end
	totalWeight = sum
	return sum
end

-- Display percentage for a trait, e.g. 0.02 meaning 0.02%.
function Traits.chancePercent(id: TraitId): number
	return Traits.get(id).Weight / Traits.totalWeight() * 100
end

-- Human-readable modifier lines, e.g. { "+400% DMG", "+200% HP" }.
function Traits.describe(id: TraitId): { string }
	local mods = Traits.get(id).Mods
	local lines: { string } = {}

	local function pushMult(value: number?, label: string, invert: boolean?)
		if not value or value == 1 then
			return
		end
		local delta = (value - 1) * 100
		if invert then
			delta = -delta
		end
		local sign = if delta >= 0 then "+" else "-"
		table.insert(lines, `{sign}{string.format("%g", math.abs(delta))}% {label}`)
	end

	local function pushPoints(value: number?, label: string)
		if not value or value == 0 then
			return
		end
		local sign = if value >= 0 then "+" else "-"
		table.insert(lines, `{sign}{string.format("%g", math.abs(value) * 100)}% {label}`)
	end

	pushMult(mods.Damage, "DMG")
	pushMult(mods.Health, "HP")
	if mods.AttackSpeed and mods.AttackSpeed ~= 1 then
		local delta = (mods.AttackSpeed - 1) * 100
		local word = if delta >= 0 then "Faster Attacks" else "Slower Attacks"
		table.insert(lines, `{string.format("%g", math.abs(delta))}% {word}`)
	end
	pushPoints(mods.CritChance, "CRIT CHANCE")
	pushPoints(mods.CritDamage, "CRIT DMG")
	pushMult(mods.Cash, "GOLD")
	pushMult(mods.Range, "RANGE")
	if mods.Summons and mods.Summons > 1 then
		table.insert(lines, `Summons {mods.Summons} units instead of 1`)
	end

	if #lines == 0 then
		table.insert(lines, "No bonuses")
	end
	return lines
end

return Traits
