--!strict
--[[
	DataService.luau

	Profile ownership: load on join, autosave, flush on leave and on shutdown.

	Session safety
	--------------
	We take a soft session lock (a JobId + heartbeat stamped into the saved
	payload). A second server that sees a *fresh* lock refuses to load and kicks
	the player rather than forking their save. A stale lock (older than
	LockStaleAfter) is stolen, which is what makes rejoin-after-crash work.

	Every write goes through UpdateAsync so two servers racing on the same key
	cannot clobber each other's transaction.
]]

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Rarities = require(Shared.Config.Rarities)
local Upgrades = require(Shared.Config.Upgrades)
local Types = require(Shared.Types)

type Profile = Types.Profile

local DataService = {}

DataService.PROFILE_VERSION = 1
DataService.LockStaleAfter = 900 -- seconds

local store: DataStore? = nil
local profiles: { [Player]: Profile } = {}
local loading: { [Player]: boolean } = {}
local dirty: { [Player]: boolean } = {}
local shuttingDown = false

-- Studio without API access still needs to be playable, so we fall back to an
-- in-memory store and say so loudly once.
local persistenceEnabled = true

--------------------------------------------------------------------------------
-- Defaults
--------------------------------------------------------------------------------

local function defaultProfile(): Profile
	local upgradeState: Types.UpgradeState = {}
	for _, id in Upgrades.Order do
		upgradeState[id] = 1
	end

	local pity: { [Rarities.RarityId]: number } = {}
	for _, id in Rarities.PityOrder do
		pity[id] = 0
	end

	return {
		Version = DataService.PROFILE_VERSION,
		Gold = GameConfig.Economy.StartingGold,
		Gems = GameConfig.Economy.StartingGems,
		Inventory = {},
		InventoryCount = 0,
		Loadout = {},
		Upgrades = upgradeState,
		Items = {},
		Index = {},
		IndexCount = 0,
		Pity = pity,
		Shop = {
			Slots = {},
			PaidRefreshes = 0,
			NextFreeRefresh = 0,
			NextRefreshCost = 0,
		},
		Stats = {
			Rolls = 0,
			HighestWave = 0,
			HighestGold = 0,
			TotalKills = 0,
			HighestTower = 0,
		},
		RedeemedCodes = {},
		Passes = {},
		LastSeen = os.time(),
		NextUid = 1,
	}
end

DataService.defaultProfile = defaultProfile

--[[
	Reconcile a loaded profile against the current default shape. New fields added
	in a later release land here instead of erroring on a nil index.
]]
local function reconcile(loaded: any): Profile
	local base = defaultProfile()

	if type(loaded) ~= "table" then
		return base
	end

	for key, value in base do
		if loaded[key] == nil then
			loaded[key] = value
		end
	end

	-- Nested tables need their own pass.
	for _, id in Upgrades.Order do
		if type(loaded.Upgrades[id]) ~= "number" then
			loaded.Upgrades[id] = 1
		end
	end
	for _, id in Rarities.PityOrder do
		if type(loaded.Pity[id]) ~= "number" then
			loaded.Pity[id] = 0
		end
	end
	for key, value in base.Stats do
		if type(loaded.Stats[key]) ~= "number" then
			loaded.Stats[key] = value
		end
	end
	if type(loaded.Shop) ~= "table" or type(loaded.Shop.Slots) ~= "table" then
		loaded.Shop = base.Shop
	end

	-- InventoryCount and IndexCount are denormalised for O(1) capacity checks;
	-- recount on load so a corrupted counter cannot lock a player out.
	local invCount = 0
	for _ in loaded.Inventory do
		invCount += 1
	end
	loaded.InventoryCount = invCount

	local indexCount = 0
	for _ in loaded.Index do
		indexCount += 1
	end
	loaded.IndexCount = indexCount

	loaded.Version = DataService.PROFILE_VERSION
	return loaded :: Profile
end

--------------------------------------------------------------------------------
-- Store access
--------------------------------------------------------------------------------

local function keyFor(player: Player): string
	return `player_{player.UserId}`
end

local function getStore(): DataStore?
	if not persistenceEnabled then
		return nil
	end
	if store then
		return store
	end
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(GameConfig.DataStoreName, GameConfig.DataStoreScope)
	end)
	if ok and result then
		store = result
		return result
	end
	persistenceEnabled = false
	warn("[DataService] DataStores unavailable — running with in-memory profiles only.")
	return nil
end

local function lockIsHeldElsewhere(payload: any): boolean
	if type(payload) ~= "table" or type(payload.Lock) ~= "table" then
		return false
	end
	local lock = payload.Lock
	if lock.JobId == game.JobId then
		return false
	end
	local age = os.time() - (tonumber(lock.Stamp) or 0)
	return age < DataService.LockStaleAfter
end

--------------------------------------------------------------------------------
-- Load / save
--------------------------------------------------------------------------------

local function loadProfile(player: Player): Profile?
	local dataStore = getStore()
	if not dataStore then
		return defaultProfile()
	end

	local result: Profile? = nil
	local blocked = false

	local ok, err = pcall(function()
		dataStore:UpdateAsync(keyFor(player), function(payload)
			if lockIsHeldElsewhere(payload) then
				blocked = true
				return nil -- abort the write, leave the record untouched
			end

			local data = if type(payload) == "table" then payload.Data else nil
			result = reconcile(data)

			return {
				Data = result,
				Lock = { JobId = game.JobId, Stamp = os.time() },
			}
		end)
	end)

	if blocked then
		return nil
	end
	if not ok then
		warn(`[DataService] load failed for {player.Name}: {err}`)
		return nil
	end
	return result
end

--[[
	Persist a profile. `release` clears the session lock so another server can
	pick the player up immediately.
]]
local function saveProfile(player: Player, profile: Profile, release: boolean): boolean
	local dataStore = getStore()
	if not dataStore then
		return true
	end

	profile.LastSeen = os.time()

	local ok, err = pcall(function()
		dataStore:UpdateAsync(keyFor(player), function(payload)
			-- Refuse to overwrite a record another live server has taken over.
			if lockIsHeldElsewhere(payload) then
				return nil
			end
			return {
				Data = profile,
				Lock = if release then nil else { JobId = game.JobId, Stamp = os.time() },
			}
		end)
	end)

	if not ok then
		warn(`[DataService] save failed for {player.Name}: {err}`)
		return false
	end
	return true
end

--------------------------------------------------------------------------------
-- Public API
--------------------------------------------------------------------------------

--[[
	Returns the profile for a player, or nil if it is still loading / failed.
	Callers on the remote path should use `expect` instead and bail on nil.
]]
function DataService.get(player: Player): Profile?
	return profiles[player]
end

-- Blocks (up to `timeout`) until the profile is available.
function DataService.wait(player: Player, timeout: number?): Profile?
	local deadline = os.clock() + (timeout or 15)
	while os.clock() < deadline do
		local profile = profiles[player]
		if profile then
			return profile
		end
		if not loading[player] and not player.Parent then
			return nil
		end
		task.wait(0.1)
	end
	return profiles[player]
end

-- Flags the profile for the next autosave pass.
function DataService.markDirty(player: Player)
	dirty[player] = true
end

function DataService.flush(player: Player, release: boolean?): boolean
	local profile = profiles[player]
	if not profile then
		return false
	end
	dirty[player] = false
	return saveProfile(player, profile, release or false)
end

--------------------------------------------------------------------------------
-- Lifecycle
--------------------------------------------------------------------------------

local onLoadedCallbacks: { (Player, Profile) -> () } = {}
local onReleasingCallbacks: { (Player, Profile) -> () } = {}

function DataService.onLoaded(callback: (Player, Profile) -> ())
	table.insert(onLoadedCallbacks, callback)
end

function DataService.onReleasing(callback: (Player, Profile) -> ())
	table.insert(onReleasingCallbacks, callback)
end

local function handlePlayerAdded(player: Player)
	loading[player] = true

	local profile: Profile? = nil
	-- Three attempts, then give up and kick rather than hand out a fresh profile
	-- that would overwrite real progress on the next save.
	for attempt = 1, 3 do
		profile = loadProfile(player)
		if profile then
			break
		end
		task.wait(attempt * 2)
	end

	loading[player] = false

	if not profile then
		if player.Parent then
			player:Kick("Could not load your save. Please rejoin in a moment — your progress is safe.")
		end
		return
	end

	-- The player may have left while we were loading.
	if not player.Parent then
		saveProfile(player, profile, true)
		return
	end

	profiles[player] = profile

	for _, callback in onLoadedCallbacks do
		local ok, err = pcall(callback, player, profile)
		if not ok then
			warn(`[DataService] onLoaded callback errored: {err}`)
		end
	end
end

local function handlePlayerRemoving(player: Player)
	local profile = profiles[player]
	if not profile then
		loading[player] = nil
		return
	end

	for _, callback in onReleasingCallbacks do
		local ok, err = pcall(callback, player, profile)
		if not ok then
			warn(`[DataService] onReleasing callback errored: {err}`)
		end
	end

	saveProfile(player, profile, true)
	profiles[player] = nil
	dirty[player] = nil
	loading[player] = nil
end

function DataService.start()
	Players.PlayerAdded:Connect(function(player)
		task.spawn(handlePlayerAdded, player)
	end)
	Players.PlayerRemoving:Connect(handlePlayerRemoving)

	-- Players who joined before this ran (shouldn't happen, but cheap to cover).
	for _, player in Players:GetPlayers() do
		if not profiles[player] and not loading[player] then
			task.spawn(handlePlayerAdded, player)
		end
	end

	-- Autosave loop.
	task.spawn(function()
		while not shuttingDown do
			task.wait(GameConfig.AutosaveInterval)
			for player, profile in profiles do
				if dirty[player] then
					dirty[player] = false
					saveProfile(player, profile, false)
					-- Spread writes so a full server doesn't burst the budget.
					task.wait(0.5)
				end
			end
		end
	end)

	game:BindToClose(function()
		shuttingDown = true
		if RunService:IsStudio() then
			return
		end

		local pending = 0
		for player, profile in profiles do
			pending += 1
			task.spawn(function()
				saveProfile(player, profile, true)
				pending -= 1
			end)
		end

		local deadline = os.clock() + 20
		while pending > 0 and os.clock() < deadline do
			task.wait(0.1)
		end
	end)
end

return DataService
