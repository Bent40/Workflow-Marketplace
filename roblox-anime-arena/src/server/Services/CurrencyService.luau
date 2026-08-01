--!strict
--[[
	CurrencyService.luau

	The only code allowed to move Gold, Gems or Items on a profile. Everything
	else asks. That keeps the audit surface small: if a currency exploit exists,
	it is in this file or in a caller that skipped it.

	Gold  — earned in-game (kills, wave clears, codes)
	Gems  — premium, bought with Robux
	Items — essences, trait shards, tickets

	Also owns the derived multipliers (luck, gold rate, slot count) because they
	are read on every kill and every roll.
]]

local Players = game:GetService("Players")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Monetization = require(Shared.Config.Monetization)
local Upgrades = require(Shared.Config.Upgrades)
local Types = require(Shared.Types)

local DataService = require(script.Parent.DataService)

type Profile = Types.Profile

local CurrencyService = {}

--------------------------------------------------------------------------------
-- Balances
--------------------------------------------------------------------------------

-- Hard ceiling so a runaway multiplier can't produce inf/NaN and corrupt a save.
local MAX_BALANCE = 1e15

local function clampBalance(value: number): number
	if value ~= value then
		return 0
	end
	return math.clamp(math.floor(value), 0, MAX_BALANCE)
end

function CurrencyService.getGold(profile: Profile): number
	return profile.Gold
end

function CurrencyService.getGems(profile: Profile): number
	return profile.Gems
end

--[[
	Add gold. `amount` may be negative, but prefer spendGold for costs so the
	"can they afford it" check and the deduction stay in one place.
]]
function CurrencyService.addGold(player: Player, profile: Profile, amount: number)
	if amount == 0 then
		return
	end
	profile.Gold = clampBalance(profile.Gold + amount)
	if profile.Gold > profile.Stats.HighestGold then
		profile.Stats.HighestGold = profile.Gold
	end
	DataService.markDirty(player)
end

-- Returns false and changes nothing when the player cannot afford `amount`.
function CurrencyService.spendGold(player: Player, profile: Profile, amount: number): boolean
	if amount <= 0 then
		return true
	end
	if profile.Gold < amount then
		return false
	end
	profile.Gold = clampBalance(profile.Gold - amount)
	DataService.markDirty(player)
	return true
end

function CurrencyService.addGems(player: Player, profile: Profile, amount: number)
	if amount == 0 then
		return
	end
	profile.Gems = clampBalance(profile.Gems + amount)
	DataService.markDirty(player)
end

function CurrencyService.spendGems(player: Player, profile: Profile, amount: number): boolean
	if amount <= 0 then
		return true
	end
	if profile.Gems < amount then
		return false
	end
	profile.Gems = clampBalance(profile.Gems - amount)
	DataService.markDirty(player)
	return true
end

--------------------------------------------------------------------------------
-- Items
--------------------------------------------------------------------------------

function CurrencyService.getItem(profile: Profile, itemId: string): number
	return profile.Items[itemId] or 0
end

function CurrencyService.addItem(player: Player, profile: Profile, itemId: string, amount: number)
	if amount == 0 then
		return
	end
	profile.Items[itemId] = clampBalance((profile.Items[itemId] or 0) + amount)
	DataService.markDirty(player)
end

function CurrencyService.spendItem(player: Player, profile: Profile, itemId: string, amount: number): boolean
	if amount <= 0 then
		return true
	end
	local held = profile.Items[itemId] or 0
	if held < amount then
		return false
	end
	profile.Items[itemId] = held - amount
	DataService.markDirty(player)
	return true
end

function CurrencyService.addItems(player: Player, profile: Profile, items: { [string]: number })
	for itemId, amount in items do
		CurrencyService.addItem(player, profile, itemId, amount)
	end
end

--------------------------------------------------------------------------------
-- Derived multipliers
--------------------------------------------------------------------------------

local function passEffect(profile: Profile, passKey: string): boolean
	return profile.Passes[passKey] == true
end

--[[
	Roll luck. Upgrade level is the main driver; the ExtraLuck pass multiplies on
	top. Used by RollService and (at reduced influence) by ShopService.
]]
function CurrencyService.getLuck(profile: Profile): number
	local luck = Upgrades.effectAt("Luck", profile.Upgrades.Luck or 1)
	if passEffect(profile, "ExtraLuck") then
		luck *= Monetization.PassEffects.ExtraLuck.LuckMultiplier
	end
	return luck
end

--[[
	Total gold multiplier: upgrade x pass x index collection bonus x friend boost.

	The friend boost counts players in this server on the local player's friends
	list, capped, matching the "Friend Gold Boost: 25%" readout in the HUD.
]]
function CurrencyService.getGoldMultiplier(player: Player, profile: Profile): number
	local multiplier = Upgrades.effectAt("Gold", profile.Upgrades.Gold or 1)

	if passEffect(profile, "DoubleGold") then
		multiplier *= Monetization.PassEffects.DoubleGold.GoldMultiplier
	end

	-- Index bonus: +5% per 5 unique units collected.
	local economy = GameConfig.Economy
	local tiers = profile.IndexCount // economy.IndexBonusPerUnits
	multiplier *= 1 + tiers * economy.IndexBonusAmount

	multiplier *= 1 + CurrencyService.getFriendBoost(player)

	return multiplier
end

-- Fraction, e.g. 0.25 for +25%.
function CurrencyService.getFriendBoost(player: Player): number
	local economy = GameConfig.Economy
	local friends = 0

	for _, other in Players:GetPlayers() do
		if other ~= player then
			local ok, isFriend = pcall(function()
				return player:IsFriendsWith(other.UserId)
			end)
			if ok and isFriend then
				friends += 1
			end
		end
	end

	return math.min(friends * economy.FriendBoostPerFriend, economy.FriendBoostCap)
end

-- Placement slots available on the player's base.
function CurrencyService.getSlots(profile: Profile): number
	local slots = Upgrades.effectAt("Slot", profile.Upgrades.Slot or 1)
	if passEffect(profile, "VIP") then
		slots += Monetization.PassEffects.VIP.ExtraSlots
	end
	return slots
end

function CurrencyService.getInventoryCapacity(profile: Profile): number
	return Upgrades.effectAt("Inventory", profile.Upgrades.Inventory or 1)
end

function CurrencyService.hasFastForward(profile: Profile): boolean
	return passEffect(profile, "FastForward")
end

function CurrencyService.hasAutoRoll(profile: Profile): boolean
	return passEffect(profile, "AutoRoll")
end

return CurrencyService
