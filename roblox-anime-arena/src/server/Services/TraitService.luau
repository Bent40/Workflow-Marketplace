--!strict
--[[
	TraitService.luau

	The Trait Machine. Spend a Trait Shard to reroll a unit's trait.

	The reroll is unconditional — it can and will replace a Mythic trait with
	None. That is the whole tension of the machine, and the client is expected to
	confirm before spending on a unit whose current trait is already good.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Rarities = require(Shared.Config.Rarities)
local Traits = require(Shared.Config.Traits)
local WeightedPick = require(Shared.Util.WeightedPick)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local TraitService = {}

local rng = Random.new()

local function rollTrait(): string
	local weights: { [string]: number } = {}
	for id, trait in Traits.Data do
		weights[id] = trait.Weight
	end
	return WeightedPick.fromMap(weights, rng) or "None"
end

function TraitService.reroll(
	player: Player,
	profile: Profile,
	uid: string
): Types.Result<{ previous: string, trait: string, improved: boolean }>
	local owned = profile.Inventory[uid]
	if not owned then
		return { ok = false, err = "You do not own that unit." }
	end

	if not CurrencyService.spendItem(player, profile, "TraitShard", Traits.RerollCost) then
		return { ok = false, err = "Not enough Trait Shards." }
	end

	local previous = owned.Trait
	local rolled = rollTrait()
	owned.Trait = rolled

	local previousRarity = Traits.get(previous).Rarity
	local rolledRarity = Traits.get(rolled).Rarity
	local improved = Rarities.isBetter(rolledRarity, previousRarity)

	DataService.markDirty(player)
	SyncService.push(player)

	if Rarities.get(rolledRarity).Broadcast then
		SyncService.announce("RareTrait", {
			PlayerName = player.DisplayName,
			UserId = player.UserId,
			UnitId = owned.Id,
			Trait = rolled,
			TraitRarity = rolledRarity,
		})
	end

	return {
		ok = true,
		data = { previous = previous, trait = rolled, improved = improved },
	}
end

-- Normalised odds for the trait index UI.
function TraitService.odds(): { [string]: number }
	local weights: { [string]: number } = {}
	for id, trait in Traits.Data do
		weights[id] = trait.Weight
	end
	return WeightedPick.probabilities(weights)
end

return TraitService
