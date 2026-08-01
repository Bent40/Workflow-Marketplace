--!strict
--[[
	InventoryService.luau

	Owns the unit collection: granting, selling, locking, merging, and the
	loadout (which units are eligible to be placed on the base).

	Merging follows the reference's rule — two units of the same id, same level
	and same mutation combine into one unit a level higher. The trait of the
	*target* is kept, so a player can level a good trait using junk copies.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Rarities = require(Shared.Config.Rarities)
local ShopConfig = require(Shared.Config.ShopConfig)
local Units = require(Shared.Config.Units)
local StatMath = require(Shared.Util.StatMath)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile
type OwnedUnit = Types.OwnedUnit

local InventoryService = {}

-- Fraction of a unit's shop value refunded when sold.
InventoryService.SellRefund = 0.35

--------------------------------------------------------------------------------
-- Granting
--------------------------------------------------------------------------------

local function nextUid(profile: Profile): string
	local uid = `u{profile.NextUid}`
	profile.NextUid += 1
	return uid
end

function InventoryService.isFull(profile: Profile): boolean
	return profile.InventoryCount >= CurrencyService.getInventoryCapacity(profile)
end

--[[
	Add a unit to the collection. Returns the new OwnedUnit, or nil when the
	inventory is full — callers decide whether that is an error (a shop purchase)
	or a silent discard (an overflowing x10 roll).
]]
function InventoryService.grant(
	player: Player,
	profile: Profile,
	unitId: Units.UnitId,
	traitId: string,
	mutationId: string,
	level: number?
): OwnedUnit?
	if not Units.get(unitId) then
		return nil
	end
	if InventoryService.isFull(profile) then
		return nil
	end

	local owned: OwnedUnit = {
		Uid = nextUid(profile),
		Id = unitId,
		Level = level or 1,
		Trait = traitId,
		Mutation = mutationId,
		Locked = false,
		Acquired = os.time(),
	}

	profile.Inventory[owned.Uid] = owned
	profile.InventoryCount += 1

	-- Index credit is permanent and independent of whether the copy survives.
	if not profile.Index[unitId] then
		profile.Index[unitId] = true
		profile.IndexCount += 1
	end

	DataService.markDirty(player)
	return owned
end

function InventoryService.get(profile: Profile, uid: string): OwnedUnit?
	return profile.Inventory[uid]
end

--------------------------------------------------------------------------------
-- Removal
--------------------------------------------------------------------------------

local function removeFromLoadout(profile: Profile, uid: string): boolean
	local removedAny = false
	for i = #profile.Loadout, 1, -1 do
		if profile.Loadout[i] == uid then
			table.remove(profile.Loadout, i)
			removedAny = true
		end
	end
	return removedAny
end

InventoryService.removeFromLoadout = removeFromLoadout

-- Low-level delete. Does not refund; callers handle payment.
local function destroy(player: Player, profile: Profile, uid: string): boolean
	if not profile.Inventory[uid] then
		return false
	end
	profile.Inventory[uid] = nil
	profile.InventoryCount = math.max(0, profile.InventoryCount - 1)
	removeFromLoadout(profile, uid)
	DataService.markDirty(player)
	return true
end

InventoryService.destroy = destroy

function InventoryService.sell(player: Player, profile: Profile, uid: string): Types.Result<{ refund: number }>
	local owned = profile.Inventory[uid]
	if not owned then
		return { ok = false, err = "You do not own that unit." }
	end
	if owned.Locked then
		return { ok = false, err = "That unit is locked. Unlock it first." }
	end

	local unit = Units.expect(owned.Id)
	local base = ShopConfig.UnitPrice[unit.Rarity] or 1000
	-- Levelled units refund proportionally to the copies invested in them.
	local refund = math.floor(base * InventoryService.SellRefund * owned.Level + 0.5)

	destroy(player, profile, uid)
	CurrencyService.addGold(player, profile, refund)
	SyncService.push(player)

	return { ok = true, data = { refund = refund } }
end

function InventoryService.toggleLock(player: Player, profile: Profile, uid: string): Types.Result<{ locked: boolean }>
	local owned = profile.Inventory[uid]
	if not owned then
		return { ok = false, err = "You do not own that unit." }
	end
	owned.Locked = not owned.Locked
	DataService.markDirty(player)
	SyncService.push(player)
	return { ok = true, data = { locked = owned.Locked } }
end

--------------------------------------------------------------------------------
-- Merging
--------------------------------------------------------------------------------

--[[
	Consume `sourceUid` to raise `targetUid` by one level.

	Both must be the same unit, the same level and the same mutation. The source
	is destroyed; the target keeps its own trait.
]]
function InventoryService.merge(
	player: Player,
	profile: Profile,
	sourceUid: string,
	targetUid: string
): Types.Result<{ level: number }>
	if sourceUid == targetUid then
		return { ok = false, err = "Pick two different copies." }
	end

	local source = profile.Inventory[sourceUid]
	local target = profile.Inventory[targetUid]
	if not source or not target then
		return { ok = false, err = "You do not own both units." }
	end
	if source.Locked then
		return { ok = false, err = "The unit being consumed is locked." }
	end
	if source.Id ~= target.Id then
		return { ok = false, err = "Both units must be the same character." }
	end
	if source.Level ~= target.Level then
		return { ok = false, err = "Both units must be the same level." }
	end
	if source.Mutation ~= target.Mutation then
		return { ok = false, err = "Both units must have the same mutation." }
	end
	if target.Level >= GameConfig.Inventory.MaxUnitLevel then
		return { ok = false, err = `Already at max level ({GameConfig.Inventory.MaxUnitLevel}).` }
	end

	destroy(player, profile, sourceUid)
	target.Level += 1
	DataService.markDirty(player)
	SyncService.push(player)

	return { ok = true, data = { level = target.Level } }
end

--------------------------------------------------------------------------------
-- Loadout
--------------------------------------------------------------------------------

function InventoryService.isInLoadout(profile: Profile, uid: string): boolean
	return table.find(profile.Loadout, uid) ~= nil
end

function InventoryService.addToLoadout(player: Player, profile: Profile, uid: string): Types.Result<nil>
	if not profile.Inventory[uid] then
		return { ok = false, err = "You do not own that unit." }
	end
	if InventoryService.isInLoadout(profile, uid) then
		return { ok = false, err = "That unit is already deployed." }
	end
	if #profile.Loadout >= CurrencyService.getSlots(profile) then
		return { ok = false, err = "No free slots. Buy a Slot Upgrade to place more." }
	end

	table.insert(profile.Loadout, uid)
	DataService.markDirty(player)
	return { ok = true }
end

--[[
	Fill every free slot with the strongest owned units, respecting each unit's
	MaxCopies. Mirrors the reference's EQUIP BEST button.
]]
function InventoryService.equipBest(player: Player, profile: Profile): Types.Result<{ equipped: number }>
	local slots = CurrencyService.getSlots(profile)

	local candidates: { OwnedUnit } = {}
	for _, owned in profile.Inventory do
		table.insert(candidates, owned)
	end
	table.sort(candidates, function(a, b)
		local pa = StatMath.power(a.Id, a.Level, a.Trait, a.Mutation)
		local pb = StatMath.power(b.Id, b.Level, b.Trait, b.Mutation)
		if pa ~= pb then
			return pa > pb
		end
		return a.Uid < b.Uid
	end)

	local loadout: { string } = {}
	local copies: { [string]: number } = {}

	for _, owned in candidates do
		if #loadout >= slots then
			break
		end
		local unit = Units.expect(owned.Id)
		local used = copies[owned.Id] or 0
		if used < unit.MaxCopies then
			copies[owned.Id] = used + 1
			table.insert(loadout, owned.Uid)
		end
	end

	profile.Loadout = loadout
	DataService.markDirty(player)
	SyncService.push(player)

	return { ok = true, data = { equipped = #loadout } }
end

--[[
	Drop loadout entries that are no longer valid — units sold or merged away, or
	slots lost. Called after anything that could invalidate the list.
]]
function InventoryService.pruneLoadout(player: Player, profile: Profile)
	local slots = CurrencyService.getSlots(profile)
	local pruned: { string } = {}

	for _, uid in profile.Loadout do
		if profile.Inventory[uid] and #pruned < slots then
			table.insert(pruned, uid)
		end
	end

	if #pruned ~= #profile.Loadout then
		profile.Loadout = pruned
		DataService.markDirty(player)
	end
end

--------------------------------------------------------------------------------
-- Queries
--------------------------------------------------------------------------------

-- Count of owned copies of a unit id, used for MaxCopies enforcement.
function InventoryService.countOf(profile: Profile, unitId: Units.UnitId): number
	local count = 0
	for _, owned in profile.Inventory do
		if owned.Id == unitId then
			count += 1
		end
	end
	return count
end

-- Highest rarity the player has ever owned; drives some UI framing.
function InventoryService.bestRarity(profile: Profile): Rarities.RarityId?
	local best: Rarities.RarityId? = nil
	for unitId in profile.Index do
		local unit = Units.get(unitId)
		if unit and (not best or Rarities.isBetter(unit.Rarity, best)) then
			best = unit.Rarity
		end
	end
	return best
end

return InventoryService
