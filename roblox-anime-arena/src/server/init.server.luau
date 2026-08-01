--!strict
--[[
	init.server.luau

	Server bootstrap. Builds the remote surface, starts services in dependency
	order, then binds every remote handler.

	Handler contract
	----------------
	Every RemoteFunction handler:
	  1. passes the rate limiter,
	  2. resolves the caller's profile (refusing if it is still loading),
	  3. validates its own arguments — a client can send anything,
	  4. returns a Types.Result, never an error.

	A handler that throws would surface as an opaque failure on the client, so
	the dispatcher wraps every call in pcall and converts a throw into a refusal.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Net = require(Shared.Net)
local Types = require(Shared.Types)

local RateLimiter = require(script.RateLimiter)

local Services = script.Services
local BaseService = require(Services.BaseService)
local CodeService = require(Services.CodeService)
local CombatService = require(Services.CombatService)
local CurrencyService = require(Services.CurrencyService)
local DataService = require(Services.DataService)
local InventoryService = require(Services.InventoryService)
local MonetizationService = require(Services.MonetizationService)
local MutationEventService = require(Services.MutationEventService)
local RollService = require(Services.RollService)
local ShopService = require(Services.ShopService)
local SyncService = require(Services.SyncService)
local TraitService = require(Services.TraitService)
local UpgradeService = require(Services.UpgradeService)

type Profile = Types.Profile

--------------------------------------------------------------------------------
-- Boot
--------------------------------------------------------------------------------

Net.build()

-- Order matters: SyncService must be live before anything can push, and
-- BaseService builds the map that CombatService then drives.
SyncService.start()
DataService.start()
BaseService.start()
CombatService.start()
ShopService.start()
MonetizationService.start()
MutationEventService.start()

-- Push a full snapshot the moment a profile lands, and hand out a base.
DataService.onLoaded(function(player, profile)
	InventoryService.pruneLoadout(player, profile)
	SyncService.pushNow(player)
	SyncService.pushShop(player)
	BaseService.broadcastAll()
end)

--------------------------------------------------------------------------------
-- Handler dispatch
--------------------------------------------------------------------------------

type Handler = (Player, Profile, ...any) -> Types.Result<any>

local function bind(remoteName: string, handler: Handler)
	Net.func(remoteName).OnServerInvoke = function(player, ...)
		if not RateLimiter.check(player, remoteName) then
			return { ok = false, err = "Slow down a moment." }
		end

		local profile = DataService.get(player)
		if not profile then
			return { ok = false, err = "Still loading your save — try again in a second." }
		end

		local ok, result = pcall(handler, player, profile, ...)
		if not ok then
			warn(`[Server] handler "{remoteName}" errored for {player.Name}: {result}`)
			return { ok = false, err = "Something went wrong. Please try again." }
		end
		return result
	end
end

--------------------------------------------------------------------------------
-- Rolling
--------------------------------------------------------------------------------

bind("Roll", function(player, profile, count, currency)
	if type(count) ~= "number" then
		return { ok = false, err = "Invalid roll count." }
	end
	local resolved = if count > 1 then GameConfig.Roll.MultiCount else 1
	local resolvedCurrency = if currency == "Gems" then "Gems" else "Gold"
	return RollService.roll(player, profile, resolved, resolvedCurrency)
end)

--------------------------------------------------------------------------------
-- Shop
--------------------------------------------------------------------------------

bind("RefreshShop", function(player, profile, useGems)
	return ShopService.refresh(player, profile, useGems == true)
end)

bind("BuyShopSlot", function(player, profile, slotIndex)
	if type(slotIndex) ~= "number" then
		return { ok = false, err = "Invalid slot." }
	end
	return ShopService.buy(player, profile, math.floor(slotIndex))
end)

--------------------------------------------------------------------------------
-- Upgrades
--------------------------------------------------------------------------------

bind("BuyUpgrade", function(player, profile, upgradeId)
	if type(upgradeId) ~= "string" then
		return { ok = false, err = "Invalid upgrade." }
	end
	return UpgradeService.buy(player, profile, upgradeId)
end)

--------------------------------------------------------------------------------
-- Inventory
--------------------------------------------------------------------------------

bind("SellUnit", function(player, profile, uid)
	if type(uid) ~= "string" then
		return { ok = false, err = "Invalid unit." }
	end
	-- Selling a placed unit has to clear the board first, or the model outlives
	-- its inventory entry and the combat loop reads a nil owner every tick.
	BaseService.onUnitRemovedFromInventory(player, uid)
	return InventoryService.sell(player, profile, uid)
end)

bind("MergeUnit", function(player, profile, sourceUid, targetUid)
	if type(sourceUid) ~= "string" or type(targetUid) ~= "string" then
		return { ok = false, err = "Invalid units." }
	end
	BaseService.onUnitRemovedFromInventory(player, sourceUid)
	return InventoryService.merge(player, profile, sourceUid, targetUid)
end)

bind("ToggleLock", function(player, profile, uid)
	if type(uid) ~= "string" then
		return { ok = false, err = "Invalid unit." }
	end
	return InventoryService.toggleLock(player, profile, uid)
end)

bind("EquipBest", function(player, profile)
	return InventoryService.equipBest(player, profile)
end)

bind("RerollTrait", function(player, profile, uid)
	if type(uid) ~= "string" then
		return { ok = false, err = "Invalid unit." }
	end
	return TraitService.reroll(player, profile, uid)
end)

--------------------------------------------------------------------------------
-- Board
--------------------------------------------------------------------------------

bind("PlaceUnit", function(player, profile, uid, position)
	if type(uid) ~= "string" or typeof(position) ~= "Vector3" then
		return { ok = false, err = "Invalid placement." }
	end
	-- Reject non-finite coordinates outright; they would poison every distance
	-- check downstream.
	if position.X ~= position.X or position.Z ~= position.Z then
		return { ok = false, err = "Invalid placement." }
	end
	return BaseService.placeUnit(player, profile, uid, position)
end)

bind("RemoveUnit", function(player, profile, uid)
	if type(uid) ~= "string" then
		return { ok = false, err = "Invalid unit." }
	end
	return BaseService.removeUnit(player, profile, uid)
end)

--------------------------------------------------------------------------------
-- Waves
--------------------------------------------------------------------------------

bind("StartWave", function(player)
	return CombatService.startWave(player)
end)

bind("StopWave", function(player)
	return CombatService.stopWave(player)
end)

bind("SetAutoWave", function(player, _profile, enabled)
	return CombatService.setAutoWave(player, enabled == true)
end)

--------------------------------------------------------------------------------
-- Misc
--------------------------------------------------------------------------------

bind("RedeemCode", function(player, profile, code)
	if type(code) ~= "string" then
		return { ok = false, err = "Enter a code." }
	end
	return CodeService.redeem(player, profile, code)
end)

bind("PromptPurchase", function(player, _profile, productKey)
	if type(productKey) ~= "string" then
		return { ok = false, err = "Unknown product." }
	end
	return MonetizationService.prompt(player, productKey)
end)

bind("GetSnapshot", function(player, profile)
	ShopService.ensure(player, profile)
	return {
		ok = true,
		data = {
			Profile = SyncService.buildSnapshot(player, profile),
			Shop = profile.Shop,
			Bases = (function()
				local infos = {}
				for _, state in BaseService.all() do
					table.insert(infos, BaseService.toInfo(state))
				end
				return infos
			end)(),
			Odds = RollService.oddsFor(profile),
			Pity = RollService.pityRemaining(profile),
			FriendBoost = CurrencyService.getFriendBoost(player),
			MutationEventEndsAt = MutationEventService.endsAt(),
		},
	}
end)

print("[AnimeArena] Server ready — 8 bases online.")
