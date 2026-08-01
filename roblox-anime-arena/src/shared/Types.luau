--!strict
--[[
	Types.luau

	Shared shapes that cross the client/server boundary. Keeping them in one place
	means the replicated snapshot and the profile can't drift apart silently.
]]

local Rarities = require(script.Parent.Config.Rarities)
local Units = require(script.Parent.Config.Units)
local Traits = require(script.Parent.Config.Traits)
local Mutations = require(script.Parent.Config.Mutations)
local Upgrades = require(script.Parent.Config.Upgrades)

export type UnitInstanceId = string

-- One owned copy of a unit. `Uid` is unique per profile.
export type OwnedUnit = {
	Uid: UnitInstanceId,
	Id: Units.UnitId,
	Level: number,
	Trait: Traits.TraitId,
	Mutation: Mutations.MutationId,
	Locked: boolean,
	-- Server timestamp of acquisition, used for "new!" badges and sort order.
	Acquired: number,
}

-- A unit currently deployed on a base.
export type PlacedUnit = {
	Uid: UnitInstanceId,
	Id: Units.UnitId,
	SlotIndex: number,
	Position: Vector3,
}

export type ShopSlot = {
	Index: number,
	UnitId: Units.UnitId,
	Rarity: Rarities.RarityId,
	Mutation: Mutations.MutationId,
	Price: number,
	Discount: number,
	SoldOut: boolean,
}

export type ShopState = {
	Slots: { ShopSlot },
	PaidRefreshes: number,
	NextFreeRefresh: number,
	NextRefreshCost: number,
}

export type UpgradeState = { [Upgrades.UpgradeId]: number }

export type PlayerStats = {
	Rolls: number,
	HighestWave: number,
	HighestGold: number,
	TotalKills: number,
	HighestTower: number,
}

-- The full server-owned profile. Persisted verbatim (minus transient fields).
export type Profile = {
	Version: number,
	Gold: number,
	Gems: number,
	Inventory: { [UnitInstanceId]: OwnedUnit },
	InventoryCount: number,
	Loadout: { UnitInstanceId },
	Upgrades: UpgradeState,
	Items: { [string]: number },
	Index: { [Units.UnitId]: boolean },
	IndexCount: number,
	Pity: { [Rarities.RarityId]: number },
	Shop: ShopState,
	Stats: PlayerStats,
	RedeemedCodes: { [string]: boolean },
	Passes: { [string]: boolean },
	LastSeen: number,
	NextUid: number,
}

-- Trimmed profile sent to the owning client. Never sent to other players.
export type ProfileSnapshot = {
	Gold: number,
	Gems: number,
	Inventory: { OwnedUnit },
	InventoryCount: number,
	InventoryCapacity: number,
	Loadout: { UnitInstanceId },
	Upgrades: UpgradeState,
	Items: { [string]: number },
	Index: { Units.UnitId },
	Pity: { [Rarities.RarityId]: number },
	Stats: PlayerStats,
	Passes: { [string]: boolean },
	Luck: number,
	GoldMultiplier: number,
	Slots: number,
}

export type RollResult = {
	UnitId: Units.UnitId,
	Rarity: Rarities.RarityId,
	Trait: Traits.TraitId,
	Mutation: Mutations.MutationId,
	Uid: UnitInstanceId?,
	-- True when pity forced this tier.
	Pitied: boolean,
	-- False when the roll was discarded because the inventory was full.
	Kept: boolean,
}

export type BaseInfo = {
	Index: number,
	OwnerUserId: number?,
	OwnerName: string?,
	Wave: number,
	Running: boolean,
	Integrity: number,
	MaxIntegrity: number,
	EnemiesLeft: number,
	EnemiesTotal: number,
}

-- Result envelope for every request-style remote. Services never throw across
-- the boundary; they return one of these.
export type Result<T> = {
	ok: boolean,
	err: string?,
	data: T?,
}

return {}
