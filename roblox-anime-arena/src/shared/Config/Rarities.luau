--!strict
--[[
	Rarities.luau

	The rarity ladder. Every unit, trait and essence hangs off one of these tiers.

	`Weight` is the raw roll weight at Luck 1.0. `LuckBias` controls how much the
	player's luck multiplier moves that weight: Common has a negative bias so it
	shrinks as luck rises, while the top tiers scale up. This keeps the curve
	well-behaved instead of just multiplying everything and re-normalising.
]]

export type RarityId = "Common" | "Rare" | "Epic" | "Legendary" | "Mythic" | "Secret" | "God"

export type Rarity = {
	Id: RarityId,
	Order: number,
	Display: string,
	Weight: number,
	LuckBias: number,
	Color: Color3,
	-- Multiplier applied to gold earned when a unit of this rarity lands a kill.
	BountyMultiplier: number,
	-- Chance that a roll of this rarity is announced to the whole server.
	Broadcast: boolean,
}

local Rarities = {}

Rarities.Order = { "Common", "Rare", "Epic", "Legendary", "Mythic", "Secret", "God" } :: { RarityId }

Rarities.Data = {
	Common = {
		Id = "Common",
		Order = 1,
		Display = "Common",
		Weight = 1000,
		LuckBias = -0.55,
		Color = Color3.fromRGB(176, 182, 196),
		BountyMultiplier = 1.0,
		Broadcast = false,
	},
	Rare = {
		Id = "Rare",
		Order = 2,
		Display = "Rare",
		Weight = 420,
		LuckBias = -0.15,
		Color = Color3.fromRGB(80, 160, 255),
		BountyMultiplier = 1.15,
		Broadcast = false,
	},
	Epic = {
		Id = "Epic",
		Order = 3,
		Display = "Epic",
		Weight = 120,
		LuckBias = 0.25,
		Color = Color3.fromRGB(168, 96, 255),
		BountyMultiplier = 1.35,
		Broadcast = false,
	},
	Legendary = {
		Id = "Legendary",
		Order = 4,
		Display = "Legendary",
		Weight = 28,
		LuckBias = 0.65,
		Color = Color3.fromRGB(255, 190, 60),
		BountyMultiplier = 1.6,
		Broadcast = false,
	},
	Mythic = {
		Id = "Mythic",
		Order = 5,
		Display = "Mythic",
		Weight = 6.5,
		LuckBias = 0.9,
		Color = Color3.fromRGB(255, 88, 132),
		BountyMultiplier = 2.0,
		Broadcast = true,
	},
	Secret = {
		Id = "Secret",
		Order = 6,
		Display = "Secret",
		Weight = 0.85,
		LuckBias = 1.0,
		Color = Color3.fromRGB(64, 240, 214),
		BountyMultiplier = 2.6,
		Broadcast = true,
	},
	God = {
		Id = "God",
		Order = 7,
		Display = "God",
		Weight = 0.08,
		LuckBias = 1.0,
		Color = Color3.fromRGB(255, 246, 168),
		BountyMultiplier = 3.4,
		Broadcast = true,
	},
} :: { [RarityId]: Rarity }

--[[
	Pity thresholds: after this many rolls without seeing the tier, the next roll
	is forced to it. Mirrors the "Legendary in 37 rolls" counter in the HUD.
]]
Rarities.Pity = {
	Legendary = 40,
	Mythic = 90,
	Secret = 240,
	God = 900,
} :: { [RarityId]: number }

-- Tiers that participate in the pity system, weakest first. Order matters:
-- the weakest satisfied pity wins so a player never burns God pity on a
-- Legendary guarantee.
Rarities.PityOrder = { "Legendary", "Mythic", "Secret", "God" } :: { RarityId }

function Rarities.get(id: RarityId): Rarity
	local rarity = Rarities.Data[id]
	assert(rarity, `Rarities.get: unknown rarity "{tostring(id)}"`)
	return rarity
end

function Rarities.color(id: RarityId): Color3
	return Rarities.get(id).Color
end

-- True when `a` is a strictly better tier than `b`.
function Rarities.isBetter(a: RarityId, b: RarityId): boolean
	return Rarities.get(a).Order > Rarities.get(b).Order
end

--[[
	Roll weight for a rarity at a given luck multiplier.

	luck 1.0 returns the base weight. Above that, tiers scale by their bias:
	positive bias tiers grow with luck, negative bias tiers shrink toward it.
]]
function Rarities.weightAtLuck(id: RarityId, luck: number): number
	local rarity = Rarities.get(id)
	local excess = math.max(luck, 1) - 1
	if excess <= 0 then
		return rarity.Weight
	end

	if rarity.LuckBias >= 0 then
		return rarity.Weight * (1 + excess * rarity.LuckBias)
	end

	-- Negative bias: decay toward a floor rather than crossing zero.
	local decay = 1 / (1 + excess * -rarity.LuckBias)
	return rarity.Weight * decay
end

return Rarities
