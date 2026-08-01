--!strict
--[[
	UpgradeService.luau

	The four permanent gold sinks. Buying a Slot upgrade widens the board; buying
	an Inventory upgrade widens storage; both can change what the loadout is
	allowed to hold, so the loadout is re-pruned after every purchase.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Upgrades = require(Shared.Config.Upgrades)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local InventoryService = require(script.Parent.InventoryService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local UpgradeService = {}

function UpgradeService.buy(
	player: Player,
	profile: Profile,
	upgradeId: string
): Types.Result<{ level: number, nextCost: number? }>
	local config = Upgrades.Data[upgradeId]
	if not config then
		return { ok = false, err = "Unknown upgrade." }
	end

	local level = profile.Upgrades[upgradeId :: Upgrades.UpgradeId] or 1
	local cost = Upgrades.costToNext(upgradeId :: Upgrades.UpgradeId, level)
	if not cost then
		return { ok = false, err = "Already at max level." }
	end

	if not CurrencyService.spendGold(player, profile, cost) then
		return { ok = false, err = "Not enough Gold." }
	end

	local newLevel = level + 1
	profile.Upgrades[upgradeId :: Upgrades.UpgradeId] = newLevel

	-- A Slot upgrade only ever adds slots, but Inventory upgrades can be bought
	-- while the loadout holds stale uids, so re-prune either way.
	InventoryService.pruneLoadout(player, profile)

	DataService.markDirty(player)
	SyncService.push(player)

	return {
		ok = true,
		data = {
			level = newLevel,
			nextCost = Upgrades.costToNext(upgradeId :: Upgrades.UpgradeId, newLevel),
		},
	}
end

return UpgradeService
