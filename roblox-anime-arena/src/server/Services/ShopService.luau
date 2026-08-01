--!strict
--[[
	ShopService.luau

	The refreshable unit shop: six slots, rerolled on demand.

	Design intent
	-------------
	Rolling is the lottery; the shop is the *deterministic* path. You can see what
	you would get and decide whether to pay for it. To stop a rich player from
	simply spinning until a God unit appears, the gold cost of each refresh within
	a free-refresh interval escalates geometrically (ShopConfig.RefreshCostGrowth),
	and the counter only resets when the free refresh comes back.

	Slots persist on the profile, so the shop a player left is the shop they
	return to — including anything they already bought (marked sold out).
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Mutations = require(Shared.Config.Mutations)
local Rarities = require(Shared.Config.Rarities)
local ShopConfig = require(Shared.Config.ShopConfig)
local Units = require(Shared.Config.Units)
local WeightedPick = require(Shared.Util.WeightedPick)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local InventoryService = require(script.Parent.InventoryService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local ShopService = {}

local rng = Random.new()

--------------------------------------------------------------------------------
-- Slot generation
--------------------------------------------------------------------------------

local function rollShopRarity(luck: number): Rarities.RarityId
	-- Shop luck is deliberately damped: the shop should stay a reliable mid-tier
	-- supply even for a maxed-luck player, not turn into a second jackpot.
	local damped = 1 + (math.max(luck, 1) - 1) * ShopConfig.LuckInfluence

	local weights: { [Rarities.RarityId]: number } = {}
	for id, base in ShopConfig.RarityWeights do
		local rarity = Rarities.get(id)
		if rarity.LuckBias >= 0 then
			weights[id] = base * (1 + (damped - 1) * rarity.LuckBias)
		else
			weights[id] = base / (1 + (damped - 1) * -rarity.LuckBias)
		end
	end
	return WeightedPick.fromMap(weights, rng) or "Common"
end

local function rollShopUnit(rarity: Rarities.RarityId): Units.UnitId
	local bucket = Units.ofRarity(rarity)
	if #bucket == 0 then
		bucket = Units.ofRarity("Common")
	end
	local weights: { [Units.UnitId]: number } = {}
	for _, unitId in bucket do
		weights[unitId] = Units.expect(unitId).Weight
	end
	return WeightedPick.fromMap(weights, rng) or bucket[1]
end

local function rollShopMutation(): string
	if rng:NextNumber() > ShopConfig.MutationChance then
		return "None"
	end
	local weights: { [string]: number } = {}
	for id, mutation in Mutations.Data do
		if id ~= "None" then
			weights[id] = mutation.Weight
		end
	end
	return WeightedPick.fromMap(weights, rng) or "None"
end

local function buildSlot(index: number, luck: number): Types.ShopSlot
	local rarity = rollShopRarity(luck)
	local unitId = rollShopUnit(rarity)
	local mutation = rollShopMutation()

	local discount = 0
	if rng:NextNumber() < ShopConfig.DiscountChance then
		discount = rng:NextNumber(ShopConfig.DiscountRange[1], ShopConfig.DiscountRange[2])
		-- Keep the displayed percentage tidy.
		discount = math.floor(discount * 100 + 0.5) / 100
	end

	local price = ShopConfig.priceFor(rarity, discount)
	-- A pre-mutated slot is worth more, and should cost more.
	if mutation ~= "None" then
		price = math.floor(price * (1 + Mutations.get(mutation).Damage * 0.35) + 0.5)
	end

	return {
		Index = index,
		UnitId = unitId,
		Rarity = rarity,
		Mutation = mutation,
		Price = price,
		Discount = discount,
		SoldOut = false,
	}
end

--------------------------------------------------------------------------------
-- Shop state
--------------------------------------------------------------------------------

local function regenerate(profile: Profile, luck: number)
	local slots: { Types.ShopSlot } = {}
	for i = 1, ShopConfig.SlotCount do
		table.insert(slots, buildSlot(i, luck))
	end
	profile.Shop.Slots = slots
end

--[[
	Roll the free-refresh timer forward if it has elapsed, resetting the paid
	refresh counter. Returns true when a free refresh was applied.

	Called lazily rather than on a timer so an offline player's shop is correct
	the instant they come back.
]]
local function applyFreeRefreshIfDue(profile: Profile, luck: number): boolean
	local now = os.time()
	if now < profile.Shop.NextFreeRefresh and #profile.Shop.Slots > 0 then
		return false
	end

	regenerate(profile, luck)
	profile.Shop.PaidRefreshes = 0
	profile.Shop.NextFreeRefresh = now + ShopConfig.FreeRefreshInterval
	return true
end

local function syncDerived(profile: Profile)
	profile.Shop.NextRefreshCost = ShopConfig.refreshCost(profile.Shop.PaidRefreshes)
end

--[[
	Called on join and whenever the client opens the shop. Safe to call often.
]]
function ShopService.ensure(player: Player, profile: Profile): Types.ShopState
	local luck = CurrencyService.getLuck(profile)
	local changed = applyFreeRefreshIfDue(profile, luck)
	syncDerived(profile)
	if changed then
		DataService.markDirty(player)
		SyncService.pushShop(player)
	end
	return profile.Shop
end

--------------------------------------------------------------------------------
-- Refresh
--------------------------------------------------------------------------------

function ShopService.refresh(player: Player, profile: Profile, useGems: boolean): Types.Result<Types.ShopState>
	local luck = CurrencyService.getLuck(profile)

	-- A due free refresh is always taken first, even if the player asked to pay.
	if applyFreeRefreshIfDue(profile, luck) then
		syncDerived(profile)
		DataService.markDirty(player)
		SyncService.pushShop(player)
		SyncService.push(player)
		return { ok = true, data = profile.Shop }
	end

	if useGems then
		if not CurrencyService.spendGems(player, profile, ShopConfig.GemRefreshCost) then
			return { ok = false, err = "Not enough Gems." }
		end
	else
		local cost = ShopConfig.refreshCost(profile.Shop.PaidRefreshes)
		if not CurrencyService.spendGold(player, profile, cost) then
			return { ok = false, err = "Not enough Gold to refresh." }
		end
		-- Only gold refreshes escalate the price; gems are a flat bypass.
		profile.Shop.PaidRefreshes += 1
	end

	regenerate(profile, luck)
	syncDerived(profile)
	DataService.markDirty(player)
	SyncService.pushShop(player)
	SyncService.push(player)

	return { ok = true, data = profile.Shop }
end

--------------------------------------------------------------------------------
-- Purchase
--------------------------------------------------------------------------------

function ShopService.buy(player: Player, profile: Profile, slotIndex: number): Types.Result<{ uid: string }>
	if type(slotIndex) ~= "number" then
		return { ok = false, err = "Invalid slot." }
	end

	ShopService.ensure(player, profile)

	local slot = profile.Shop.Slots[slotIndex]
	if not slot or slot.Index ~= slotIndex then
		-- Index mismatch means the shop refreshed under the player; re-find it.
		slot = nil
		for _, candidate in profile.Shop.Slots do
			if candidate.Index == slotIndex then
				slot = candidate
				break
			end
		end
	end

	if not slot then
		return { ok = false, err = "That slot no longer exists." }
	end
	if slot.SoldOut then
		return { ok = false, err = "Already sold out." }
	end
	if InventoryService.isFull(profile) then
		return { ok = false, err = "Inventory full — sell something or upgrade capacity." }
	end

	if not CurrencyService.spendGold(player, profile, slot.Price) then
		return { ok = false, err = "Not enough Gold." }
	end

	-- Shop units come with no trait; the Trait Machine is a separate sink.
	local owned = InventoryService.grant(player, profile, slot.UnitId, "None", slot.Mutation)
	if not owned then
		-- Refund rather than eat the gold: unlike a roll, a shop purchase is a
		-- deliberate, priced transaction and must be all-or-nothing.
		CurrencyService.addGold(player, profile, slot.Price)
		return { ok = false, err = "Inventory full — purchase refunded." }
	end

	slot.SoldOut = true
	DataService.markDirty(player)
	SyncService.pushShop(player)
	SyncService.push(player)

	return { ok = true, data = { uid = owned.Uid } }
end

--------------------------------------------------------------------------------
-- Lifecycle
--------------------------------------------------------------------------------

function ShopService.start()
	DataService.onLoaded(function(player, profile)
		ShopService.ensure(player, profile)
	end)
end

return ShopService
