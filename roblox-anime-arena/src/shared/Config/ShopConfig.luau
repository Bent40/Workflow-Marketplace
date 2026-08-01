--!strict
--[[
	ShopConfig.luau

	The refreshable unit shop.

	Six slots are drawn from the roster. Refreshing rerolls all six. The first
	refresh on each timer tick is free; after that the gold price escalates within
	the tick and resets when the free refresh comes back. That escalation is what
	stops a player with a large bank from just spinning the shop until a God unit
	appears — and it is why the shop needs its own rarity table, tilted much
	flatter than the roll table.
]]

local Rarities = require(script.Parent.Rarities)

local ShopConfig = {}

ShopConfig.SlotCount = 6

-- Seconds between free refreshes.
ShopConfig.FreeRefreshInterval = 300

-- Gold price of the Nth paid refresh within one interval.
ShopConfig.RefreshBaseCost = 2500
ShopConfig.RefreshCostGrowth = 1.85
ShopConfig.RefreshCostCap = 750000

-- Gem price for an instant refresh that ignores the escalating gold cost.
ShopConfig.GemRefreshCost = 15

--[[
	Shop rarity weights. Note these are *much* flatter than Rarities.Weight: the
	shop is the deterministic path to a good unit ("I can see it and I can afford
	it"), while rolling is the lottery. Keeping them on separate tables lets us
	tune one without disturbing the other.
]]
ShopConfig.RarityWeights = {
	Common = 320,
	Rare = 240,
	Epic = 120,
	Legendary = 42,
	Mythic = 11,
	Secret = 2.2,
	God = 0.22,
} :: { [Rarities.RarityId]: number }

-- Luck affects the shop, but at a reduced rate compared to rolling.
ShopConfig.LuckInfluence = 0.45

--[[
	Gold price of a shop unit, by rarity. These are priced so that a Legendary is
	roughly ten waves of income in the midgame — expensive enough to be a real
	decision, cheap enough that the shop stays the reliable pity valve.
]]
ShopConfig.UnitPrice = {
	Common = 1200,
	Rare = 6500,
	Epic = 32000,
	Legendary = 165000,
	Mythic = 900000,
	Secret = 5200000,
	God = 42000000,
} :: { [Rarities.RarityId]: number }

-- Chance a given slot rolls with a discount, and the discount band.
ShopConfig.DiscountChance = 0.22
ShopConfig.DiscountRange = { 0.15, 0.45 }

-- Chance a shop slot comes pre-rolled with a mutation, by rarity floor.
ShopConfig.MutationChance = 0.12

-- A slot is consumed once bought; it shows as sold out until the next refresh.
ShopConfig.SoldOutPersists = true

function ShopConfig.refreshCost(paidRefreshesThisInterval: number): number
	local cost = ShopConfig.RefreshBaseCost * ShopConfig.RefreshCostGrowth ^ paidRefreshesThisInterval
	return math.min(math.floor(cost + 0.5), ShopConfig.RefreshCostCap)
end

function ShopConfig.priceFor(rarity: Rarities.RarityId, discount: number?): number
	local base = ShopConfig.UnitPrice[rarity] or 1000
	local finalPrice = base * (1 - (discount or 0))
	return math.max(1, math.floor(finalPrice + 0.5))
end

return ShopConfig
