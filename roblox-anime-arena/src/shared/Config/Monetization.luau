--!strict
--[[
	Monetization.luau

	Robux products. `Id` values are placeholders — replace each one with the real
	asset id from the Creator Dashboard before publishing. MonetizationService
	refuses to process an unconfigured (0) id rather than silently granting.

	Two currencies, as designed:
	  Gold  — earned in-game from kills and wave clears.
	  Gems  — bought with Robux (or handed out by codes/rewards), spent on
	          instant refreshes, gem rolls, and premium bundles.
]]

export type ProductKind = "Gems" | "Bundle" | "Item"

export type DevProduct = {
	Key: string,
	Id: number,
	Display: string,
	Kind: ProductKind,
	RobuxPrice: number, -- display only; Roblox is the source of truth
	Gems: number?,
	Items: { [string]: number }?,
	Gold: number?,
	Badge: string?,
	Order: number,
}

export type GamePass = {
	Key: string,
	Id: number,
	Display: string,
	Description: string,
	RobuxPrice: number,
	Order: number,
}

local Monetization = {}

Monetization.DevProducts = {
	Gems100 = {
		Key = "Gems100",
		Id = 0,
		Display = "100 Gems",
		Kind = "Gems",
		RobuxPrice = 99,
		Gems = 100,
		Order = 1,
	},
	Gems550 = {
		Key = "Gems550",
		Id = 0,
		Display = "550 Gems",
		Kind = "Gems",
		RobuxPrice = 499,
		Gems = 550,
		Badge = "POPULAR!",
		Order = 2,
	},
	Gems1200 = {
		Key = "Gems1200",
		Id = 0,
		Display = "1,200 Gems",
		Kind = "Gems",
		RobuxPrice = 999,
		Gems = 1200,
		Order = 3,
	},
	Gems3000 = {
		Key = "Gems3000",
		Id = 0,
		Display = "3,000 Gems",
		Kind = "Gems",
		RobuxPrice = 2499,
		Gems = 3000,
		Badge = "BEST",
		Order = 4,
	},

	TraitShard1 = {
		Key = "TraitShard1",
		Id = 0,
		Display = "Trait Shard Pack",
		Kind = "Item",
		RobuxPrice = 19,
		Items = { TraitShard = 1 },
		Order = 10,
	},
	TraitShard10 = {
		Key = "TraitShard10",
		Id = 0,
		Display = "Trait Shard Pack II",
		Kind = "Item",
		RobuxPrice = 179,
		Items = { TraitShard = 10 },
		Order = 11,
	},
	TraitShard50 = {
		Key = "TraitShard50",
		Id = 0,
		Display = "Trait Shard Pack III",
		Kind = "Item",
		RobuxPrice = 899,
		Items = { TraitShard = 50 },
		Order = 12,
	},
	TraitShard100 = {
		Key = "TraitShard100",
		Id = 0,
		Display = "Trait Shard Pack IV",
		Kind = "Item",
		RobuxPrice = 1749,
		Items = { TraitShard = 100 },
		Badge = "BEST",
		Order = 13,
	},

	StarterBundle = {
		Key = "StarterBundle",
		Id = 0,
		Display = "Starter Bundle",
		Kind = "Bundle",
		RobuxPrice = 199,
		Gems = 250,
		Gold = 250000,
		Items = { TraitShard = 5 },
		Badge = "LIMITED",
		Order = 20,
	},
	MythicBundle = {
		Key = "MythicBundle",
		Id = 0,
		Display = "Mythic Bundle",
		Kind = "Bundle",
		RobuxPrice = 699,
		Gems = 900,
		Gold = 2500000,
		Items = { TraitShard = 25, MythicEssence = 10 },
		Order = 21,
	},
	GodBundle = {
		Key = "GodBundle",
		Id = 0,
		Display = "God Bundle",
		Kind = "Bundle",
		RobuxPrice = 1299,
		Gems = 1800,
		Gold = 9000000,
		Items = { TraitShard = 60, SecretEssence = 15 },
		Order = 22,
	},
} :: { [string]: DevProduct }

Monetization.GamePasses = {
	DoubleGold = {
		Key = "DoubleGold",
		Id = 0,
		Display = "2x Gold",
		Description = "Permanently doubles all gold earned.",
		RobuxPrice = 499,
		Order = 1,
	},
	AutoRoll = {
		Key = "AutoRoll",
		Id = 0,
		Display = "Auto Roll",
		Description = "Rolls for you while you defend.",
		RobuxPrice = 399,
		Order = 2,
	},
	FastForward = {
		Key = "FastForward",
		Id = 0,
		Display = "2x Speed",
		Description = "Run waves at double speed.",
		RobuxPrice = 349,
		Order = 3,
	},
	VIP = {
		Key = "VIP",
		Id = 0,
		Display = "VIP",
		Description = "+2 slots, a daily VIP chest, and a golden nametag.",
		RobuxPrice = 799,
		Order = 4,
	},
	ExtraLuck = {
		Key = "ExtraLuck",
		Id = 0,
		Display = "+50% Luck",
		Description = "Permanently boosts your roll luck.",
		RobuxPrice = 599,
		Order = 5,
	},
} :: { [string]: GamePass }

-- Passive effects granted by owned passes, read by the stat pipeline.
Monetization.PassEffects = {
	DoubleGold = { GoldMultiplier = 2 },
	FastForward = { FastForward = true },
	AutoRoll = { AutoRoll = true },
	VIP = { ExtraSlots = 2, DailyChest = true },
	ExtraLuck = { LuckMultiplier = 1.5 },
}

function Monetization.productByAssetId(assetId: number): DevProduct?
	for _, product in Monetization.DevProducts do
		if product.Id == assetId and assetId ~= 0 then
			return product
		end
	end
	return nil
end

function Monetization.orderedProducts(): { DevProduct }
	local list: { DevProduct } = {}
	for _, product in Monetization.DevProducts do
		table.insert(list, product)
	end
	table.sort(list, function(a, b)
		return a.Order < b.Order
	end)
	return list
end

function Monetization.orderedPasses(): { GamePass }
	local list: { GamePass } = {}
	for _, pass in Monetization.GamePasses do
		table.insert(list, pass)
	end
	table.sort(list, function(a, b)
		return a.Order < b.Order
	end)
	return list
end

return Monetization
