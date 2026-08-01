--!strict
--[[
	RollService.luau

	The gacha. Server-authoritative end to end: the client asks for N rolls, the
	server charges, rolls, grants and replies with the results. The client's
	animation is cosmetic — it is replaying an outcome that already happened.

	Order of operations for one roll:
	  1. pity check   — has any tier hit its guarantee?
	  2. rarity roll  — luck-weighted, if pity did not fire
	  3. unit roll    — weighted within the rarity bucket
	  4. trait roll   — independent
	  5. mutation roll — independent, inflated during a Mutation Event
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Mutations = require(Shared.Config.Mutations)
local Rarities = require(Shared.Config.Rarities)
local Traits = require(Shared.Config.Traits)
local Units = require(Shared.Config.Units)
local WeightedPick = require(Shared.Util.WeightedPick)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local InventoryService = require(script.Parent.InventoryService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local RollService = {}

-- One shared generator. Roblox seeds Random.new() from the system clock, which
-- is enough entropy here; per-player generators would only make outcomes easier
-- to predict, not harder.
local rng = Random.new()

-- Set by MutationEventService while an event is live.
local mutationEventActive = false

function RollService.setMutationEvent(active: boolean)
	mutationEventActive = active
end

function RollService.isMutationEventActive(): boolean
	return mutationEventActive
end

--------------------------------------------------------------------------------
-- Individual roll steps
--------------------------------------------------------------------------------

--[[
	Returns the tier pity guarantees on this roll, or nil.

	Weakest satisfied tier wins, so a player sitting at 240 Secret pity and 40
	Legendary pity gets the Legendary now and keeps the Secret counter running.
	That is deliberately the *less* generous reading, and it is the one that keeps
	the long-tail counters meaningful.
]]
local function checkPity(profile: Profile): Rarities.RarityId?
	for _, tier in Rarities.PityOrder do
		local threshold = Rarities.Pity[tier]
		if threshold and (profile.Pity[tier] or 0) >= threshold - 1 then
			return tier
		end
	end
	return nil
end

local function rollRarity(luck: number): Rarities.RarityId
	local weights: { [Rarities.RarityId]: number } = {}
	for _, id in Rarities.Order do
		weights[id] = Rarities.weightAtLuck(id, luck)
	end
	return WeightedPick.fromMap(weights, rng) or "Common"
end

local function rollUnit(rarity: Rarities.RarityId): Units.UnitId
	local bucket = Units.ofRarity(rarity)
	if #bucket == 0 then
		-- A rarity with no units would otherwise hard-fail a roll; degrade to Common.
		bucket = Units.ofRarity("Common")
	end

	local weights: { [Units.UnitId]: number } = {}
	for _, unitId in bucket do
		weights[unitId] = Units.expect(unitId).Weight
	end
	return WeightedPick.fromMap(weights, rng) or bucket[1]
end

local function rollTrait(): string
	local weights: { [string]: number } = {}
	for id, trait in Traits.Data do
		weights[id] = trait.Weight
	end
	return WeightedPick.fromMap(weights, rng) or "None"
end

local function rollMutation(): string
	local weights: { [string]: number } = {}
	for id, mutation in Mutations.Data do
		local weight = mutation.Weight
		if mutationEventActive and id ~= "None" then
			weight *= GameConfig.MutationEvent.WeightMultiplier
		end
		weights[id] = weight
	end
	return WeightedPick.fromMap(weights, rng) or "None"
end

--[[
	Advance pity counters after a roll.

	Every tier at or below what was rolled resets; everything above it increments.
	Rolling a Mythic therefore clears both the Legendary and Mythic counters,
	which is what players expect from the "Legendary in N rolls" display.
]]
local function updatePity(profile: Profile, rolled: Rarities.RarityId)
	local rolledOrder = Rarities.get(rolled).Order
	for _, tier in Rarities.PityOrder do
		if Rarities.get(tier).Order <= rolledOrder then
			profile.Pity[tier] = 0
		else
			profile.Pity[tier] = (profile.Pity[tier] or 0) + 1
		end
	end
end

--------------------------------------------------------------------------------
-- Public roll
--------------------------------------------------------------------------------

function RollService.cost(count: number, currency: string): number
	local roll = GameConfig.Roll
	if currency == "Gems" then
		return if count > 1 then roll.GemCostMulti else roll.GemCostSingle
	end
	if count > 1 then
		return math.floor(roll.GoldCost * count * (1 - roll.MultiDiscount) + 0.5)
	end
	return roll.GoldCost
end

--[[
	Roll `count` times. Charges once for the whole batch.

	Inventory overflow does not refund: the roll happened, the pity counters moved,
	and the index credit was awarded — the copy is just discarded. The client is
	told via `Kept = false` so it can warn the player.
]]
function RollService.roll(
	player: Player,
	profile: Profile,
	count: number,
	currency: string
): Types.Result<{ Types.RollResult }>
	local multi = GameConfig.Roll.MultiCount
	if count ~= 1 and count ~= multi then
		return { ok = false, err = "Invalid roll count." }
	end

	local price = RollService.cost(count, currency)
	if currency == "Gems" then
		if not CurrencyService.spendGems(player, profile, price) then
			return { ok = false, err = "Not enough Gems." }
		end
	else
		if not CurrencyService.spendGold(player, profile, price) then
			return { ok = false, err = "Not enough Gold." }
		end
	end

	local luck = CurrencyService.getLuck(profile)
	local results: { Types.RollResult } = {}
	local overflowed = false

	for _ = 1, count do
		local pitied = checkPity(profile)
		local rarity = pitied or rollRarity(luck)
		local unitId = rollUnit(rarity)
		local traitId = rollTrait()
		local mutationId = rollMutation()

		updatePity(profile, rarity)
		profile.Stats.Rolls += 1

		local owned = InventoryService.grant(player, profile, unitId, traitId, mutationId)
		if not owned then
			overflowed = true
		end

		table.insert(results, {
			UnitId = unitId,
			Rarity = rarity,
			Trait = traitId,
			Mutation = mutationId,
			Uid = if owned then owned.Uid else nil,
			Pitied = pitied ~= nil,
			Kept = owned ~= nil,
		})

		-- Server-wide shout for the top tiers.
		if Rarities.get(rarity).Broadcast then
			SyncService.announce("RareRoll", {
				PlayerName = player.DisplayName,
				UserId = player.UserId,
				UnitId = unitId,
				Rarity = rarity,
				Trait = traitId,
				Mutation = mutationId,
			})
		end
	end

	DataService.markDirty(player)
	SyncService.push(player)

	if overflowed then
		SyncService.toast(player, "error", "Inventory full — some units were lost! Sell or upgrade capacity.")
	end

	return { ok = true, data = results }
end

--------------------------------------------------------------------------------
-- Odds display
--------------------------------------------------------------------------------

-- Normalised rarity odds at the player's current luck, for the roll UI.
function RollService.oddsFor(profile: Profile): { [Rarities.RarityId]: number }
	local luck = CurrencyService.getLuck(profile)
	local weights: { [Rarities.RarityId]: number } = {}
	for _, id in Rarities.Order do
		weights[id] = Rarities.weightAtLuck(id, luck)
	end
	return WeightedPick.probabilities(weights)
end

-- Rolls remaining before each pity tier fires.
function RollService.pityRemaining(profile: Profile): { [Rarities.RarityId]: number }
	local out: { [Rarities.RarityId]: number } = {}
	for _, tier in Rarities.PityOrder do
		local threshold = Rarities.Pity[tier]
		if threshold then
			out[tier] = math.max(0, threshold - (profile.Pity[tier] or 0))
		end
	end
	return out
end

return RollService
