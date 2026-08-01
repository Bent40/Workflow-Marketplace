--!strict
--[[
	Items.luau

	Consumables. Essences drop from kills and feed the Clone Machine; Trait Shards
	feed the Trait Machine; tickets gate the Infinite Tower.
]]

local Rarities = require(script.Parent.Rarities)

export type ItemId = string

export type Item = {
	Id: ItemId,
	Display: string,
	Description: string,
	Color: Color3,
	Order: number,
	-- Essences are keyed to the rarity they clone.
	EssenceFor: Rarities.RarityId?,
}

local Items = {}

Items.Data = {
	TraitShard = {
		Id = "TraitShard",
		Display = "Trait Shard",
		Description = "Reroll a unit's trait at the Trait Machine.",
		Color = Color3.fromRGB(255, 196, 96),
		Order = 1,
	},
	InfiniteTicket = {
		Id = "InfiniteTicket",
		Display = "Infinite Ticket",
		Description = "Grants one entry to the Infinite Tower.",
		Color = Color3.fromRGB(120, 220, 255),
		Order = 2,
	},
	CommonEssence = {
		Id = "CommonEssence",
		Display = "Common Essence",
		Description = "Clone a Common unit.",
		Color = Rarities.Data.Common.Color,
		Order = 10,
		EssenceFor = "Common",
	},
	RareEssence = {
		Id = "RareEssence",
		Display = "Rare Essence",
		Description = "Clone a Rare unit.",
		Color = Rarities.Data.Rare.Color,
		Order = 11,
		EssenceFor = "Rare",
	},
	EpicEssence = {
		Id = "EpicEssence",
		Display = "Epic Essence",
		Description = "Clone an Epic unit.",
		Color = Rarities.Data.Epic.Color,
		Order = 12,
		EssenceFor = "Epic",
	},
	LegendaryEssence = {
		Id = "LegendaryEssence",
		Display = "Legendary Essence",
		Description = "Clone a Legendary unit.",
		Color = Rarities.Data.Legendary.Color,
		Order = 13,
		EssenceFor = "Legendary",
	},
	MythicEssence = {
		Id = "MythicEssence",
		Display = "Mythic Essence",
		Description = "Clone a Mythic unit.",
		Color = Rarities.Data.Mythic.Color,
		Order = 14,
		EssenceFor = "Mythic",
	},
	SecretEssence = {
		Id = "SecretEssence",
		Display = "Secret Essence",
		Description = "Clone a Secret unit.",
		Color = Rarities.Data.Secret.Color,
		Order = 15,
		EssenceFor = "Secret",
	},
	GodEssence = {
		Id = "GodEssence",
		Display = "God Essence",
		Description = "Clone a God unit.",
		Color = Rarities.Data.God.Color,
		Order = 16,
		EssenceFor = "God",
	},
} :: { [ItemId]: Item }

-- Essence required to clone a unit of each rarity, plus the clone duration.
Items.CloneCost = {
	Common = { Essence = "CommonEssence", Amount = 25, Seconds = 60 },
	Rare = { Essence = "RareEssence", Amount = 40, Seconds = 180 },
	Epic = { Essence = "EpicEssence", Amount = 60, Seconds = 600 },
	Legendary = { Essence = "LegendaryEssence", Amount = 90, Seconds = 1800 },
	Mythic = { Essence = "MythicEssence", Amount = 140, Seconds = 5400 },
	Secret = { Essence = "SecretEssence", Amount = 220, Seconds = 14400 },
	God = { Essence = "GodEssence", Amount = 400, Seconds = 43200 },
} :: { [Rarities.RarityId]: { Essence: ItemId, Amount: number, Seconds: number } }

-- Chance an enemy kill drops an essence, and which tier it rolls.
Items.EssenceDropChance = 0.18
Items.EssenceDropWeights = {
	Common = 1000,
	Rare = 380,
	Epic = 120,
	Legendary = 26,
	Mythic = 5,
	Secret = 0.6,
	God = 0.05,
} :: { [Rarities.RarityId]: number }

-- Trait shards drop less often but from any kill.
Items.TraitShardDropChance = 0.06

function Items.get(id: ItemId): Item?
	return Items.Data[id]
end

function Items.ordered(): { Item }
	local list: { Item } = {}
	for _, item in Items.Data do
		table.insert(list, item)
	end
	table.sort(list, function(a, b)
		return a.Order < b.Order
	end)
	return list
end

function Items.essenceFor(rarity: Rarities.RarityId): ItemId
	local entry = Items.CloneCost[rarity]
	return entry.Essence
end

return Items
