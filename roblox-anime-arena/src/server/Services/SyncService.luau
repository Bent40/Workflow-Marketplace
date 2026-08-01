--!strict
--[[
	SyncService.luau

	Builds the client-facing snapshot and pushes it. Services call
	`SyncService.push(player)` after any profile mutation; pushes are coalesced to
	one per frame so a x10 roll that touches the profile ten times still sends a
	single update.

	A snapshot only ever goes to its owner. Other players' balances and inventories
	are never replicated — the public read-outs (leaderboard, base ownership) go
	through BaseService instead.
]]

local RunService = game:GetService("RunService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Net = require(Shared.Net)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)

type Profile = Types.Profile

local SyncService = {}

local pendingProfile: { [Player]: boolean } = {}
local pendingShop: { [Player]: boolean } = {}
local started = false

--------------------------------------------------------------------------------
-- Snapshot
--------------------------------------------------------------------------------

--[[
	Convert the profile's map-shaped inventory into an array the client can sort
	without re-keying, and attach the derived numbers the UI needs so the client
	never recomputes (and never disagrees with) server truth.
]]
function SyncService.buildSnapshot(player: Player, profile: Profile): Types.ProfileSnapshot
	local inventory: { Types.OwnedUnit } = {}
	for _, owned in profile.Inventory do
		table.insert(inventory, owned)
	end
	table.sort(inventory, function(a, b)
		if a.Acquired ~= b.Acquired then
			return a.Acquired > b.Acquired
		end
		return a.Uid < b.Uid
	end)

	local index: { string } = {}
	for unitId in profile.Index do
		table.insert(index, unitId)
	end
	table.sort(index)

	return {
		Gold = profile.Gold,
		Gems = profile.Gems,
		Inventory = inventory,
		InventoryCount = profile.InventoryCount,
		InventoryCapacity = CurrencyService.getInventoryCapacity(profile),
		Loadout = table.clone(profile.Loadout),
		Upgrades = table.clone(profile.Upgrades),
		Items = table.clone(profile.Items),
		Index = index,
		Pity = table.clone(profile.Pity),
		Stats = table.clone(profile.Stats),
		Passes = table.clone(profile.Passes),
		Luck = CurrencyService.getLuck(profile),
		GoldMultiplier = CurrencyService.getGoldMultiplier(player, profile),
		Slots = CurrencyService.getSlots(profile),
	}
end

--------------------------------------------------------------------------------
-- Push
--------------------------------------------------------------------------------

-- Queue a profile push for the end of the frame.
function SyncService.push(player: Player)
	pendingProfile[player] = true
end

-- Queue a shop push for the end of the frame.
function SyncService.pushShop(player: Player)
	pendingShop[player] = true
end

-- Send immediately, skipping the coalescing queue. Used on join.
function SyncService.pushNow(player: Player)
	local profile = DataService.get(player)
	if not profile or not player.Parent then
		return
	end
	pendingProfile[player] = nil
	Net.event("ProfileUpdated"):FireClient(player, SyncService.buildSnapshot(player, profile))
end

function SyncService.toast(player: Player, kind: string, message: string)
	if not player.Parent then
		return
	end
	Net.event("Toast"):FireClient(player, kind, message)
end

-- Server-wide feed for rare pulls.
function SyncService.announce(kind: string, payload: { [string]: any })
	Net.event("Announce"):FireAllClients(kind, payload)
end

function SyncService.start()
	if started then
		return
	end
	started = true

	RunService.Heartbeat:Connect(function()
		if next(pendingProfile) == nil and next(pendingShop) == nil then
			return
		end

		local profileQueue = pendingProfile
		local shopQueue = pendingShop
		pendingProfile = {}
		pendingShop = {}

		for player in profileQueue do
			local profile = DataService.get(player)
			if profile and player.Parent then
				Net.event("ProfileUpdated"):FireClient(player, SyncService.buildSnapshot(player, profile))
			end
		end

		for player in shopQueue do
			local profile = DataService.get(player)
			if profile and player.Parent then
				Net.event("ShopUpdated"):FireClient(player, profile.Shop)
			end
		end
	end)
end

return SyncService
