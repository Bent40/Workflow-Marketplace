--!strict
--[[
	GameConfig.luau

	Global tuning knobs. Anything a designer would want to nudge without reading
	service code lives here.
]]

local GameConfig = {}

GameConfig.DataStoreName = "AnimeArena_Player_v1"
GameConfig.DataStoreScope = "live"

-- Server-authoritative save cadence. Profiles also flush on leave and shutdown.
GameConfig.AutosaveInterval = 90

--------------------------------------------------------------------------------
-- Bases
--------------------------------------------------------------------------------

GameConfig.Bases = {
	-- Eight bases per map, claimed on join and released on leave.
	Count = 8,
	-- Bases sit on a ring around the map centre.
	RingRadius = 420,
	-- Footprint of a single base plot.
	PlotSize = Vector3.new(180, 1, 180),
	-- Integrity the core starts with before any TANK contributions.
	BaseIntegrity = 1000,
	-- Placement slots unlocked at Slot upgrade level 1.
	StartingSlots = 5,
	-- A base is held for this long after its owner leaves, so a rejoin inside the
	-- grace window gets the same plot and keeps its run alive.
	ReclaimGrace = 120,
}

--------------------------------------------------------------------------------
-- Economy
--------------------------------------------------------------------------------

GameConfig.Economy = {
	StartingGold = 2500,
	StartingGems = 0,

	-- Gold granted per enemy kill = enemy bounty * these multipliers.
	FriendBoostPerFriend = 0.05,
	FriendBoostCap = 0.25,

	-- Index collection bonus: +5% gold per N unique units owned.
	IndexBonusPerUnits = 5,
	IndexBonusAmount = 0.05,

	-- Completing a wave pays a flat clear bonus scaled by wave number.
	WaveClearBase = 400,
	WaveClearGrowth = 1.18,
}

--------------------------------------------------------------------------------
-- Rolling
--------------------------------------------------------------------------------

GameConfig.Roll = {
	GoldCost = 1500,
	-- x10 costs 10x minus a small discount, matching the reference's bulk button.
	MultiCount = 10,
	MultiDiscount = 0.10,
	-- Gems shortcut for players who would rather not farm.
	GemCostSingle = 5,
	GemCostMulti = 45,
	-- Roll animation length the client is allowed to play before results show.
	RevealSeconds = 1.1,
	-- Server-side floor between rolls from one player, anti-spam.
	CooldownSeconds = 0.15,
}

--------------------------------------------------------------------------------
-- Mutation events
--------------------------------------------------------------------------------

GameConfig.MutationEvent = {
	IntervalSeconds = 15 * 60,
	DurationSeconds = 3 * 60,
	-- Non-None mutation weights are multiplied by this during an event.
	WeightMultiplier = 6,
}

--------------------------------------------------------------------------------
-- Combat
--------------------------------------------------------------------------------

GameConfig.Combat = {
	-- Server tick rate for targeting and damage. Enemy movement is interpolated
	-- on the client between ticks so 10Hz reads smoothly.
	TickRate = 10,
	-- Enemies spawn this far apart within a wave.
	SpawnInterval = 0.55,
	-- Seconds between the last kill and the next wave auto-starting.
	InterWaveDelay = 3,
	-- Speed multiplier unlocked by the 2x gamepass.
	FastForwardMultiplier = 2,
	-- Hard cap on live enemies per base, protects the server from a stall spiral.
	MaxLiveEnemies = 120,
}

--------------------------------------------------------------------------------
-- Inventory
--------------------------------------------------------------------------------

GameConfig.Inventory = {
	BaseCapacity = 125,
	CapacityPerUpgradeLevel = 25,
	-- Merging two identical units (same id, level and mutation) levels one up.
	MaxUnitLevel = 20,
	-- Stat multiplier per level above 1.
	LevelStatGrowth = 0.35,
}

--------------------------------------------------------------------------------
-- Anti-abuse
--------------------------------------------------------------------------------

GameConfig.RateLimits = {
	-- remoteName -> { calls, perSeconds }
	Roll = { 20, 5 },
	ShopRefresh = { 10, 5 },
	ShopBuy = { 20, 5 },
	PlaceUnit = { 40, 5 },
	SellUnit = { 40, 5 },
	MergeUnit = { 40, 5 },
	RerollTrait = { 20, 5 },
	BuyUpgrade = { 20, 5 },
	StartWave = { 10, 5 },
	RedeemCode = { 5, 10 },
	Default = { 30, 5 },
}

return GameConfig
