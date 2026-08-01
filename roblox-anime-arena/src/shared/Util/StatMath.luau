--!strict
--[[
	StatMath.luau

	The single source of truth for how a unit's numbers are computed. Both the
	server (for real damage) and the client (for tooltips) call in here, so a
	tooltip can never disagree with the damage the player actually deals.

	Pipeline, in order:
	  base stat
	  x level growth
	  x mutation
	  x trait
	  x support auras in range
	Crit chance and crit damage are additive percentage points, applied last.
]]

local Units = require(script.Parent.Parent.Config.Units)
local Traits = require(script.Parent.Parent.Config.Traits)
local Mutations = require(script.Parent.Parent.Config.Mutations)
local GameConfig = require(script.Parent.Parent.Config.GameConfig)

export type ComputedStats = {
	Damage: number,
	Health: number,
	AttackSpeed: number,
	Range: number,
	CritChance: number,
	CritDamage: number,
	CashMultiplier: number,
	Summons: number,
	-- Seconds between attacks, derived from AttackSpeed. Precomputed because the
	-- combat loop reads it every tick.
	Cooldown: number,
}

export type AuraTotals = {
	Damage: number,
	AttackSpeed: number,
	Range: number,
	Cash: number,
}

local StatMath = {}

StatMath.NoAura = {
	Damage = 1,
	AttackSpeed = 1,
	Range = 1,
	Cash = 1,
} :: AuraTotals

--[[
	Level multiplier. Level 1 is 1.0; each level adds LevelStatGrowth of the base,
	so a level 20 unit is (1 + 19 * 0.35) = 7.65x. Additive rather than geometric
	on purpose — geometric growth plus merging plus traits compounds far too fast.
]]
function StatMath.levelMultiplier(level: number): number
	local clamped = math.clamp(level, 1, GameConfig.Inventory.MaxUnitLevel)
	return 1 + (clamped - 1) * GameConfig.Inventory.LevelStatGrowth
end

--[[
	Combine a list of support auras into one set of multipliers.

	Auras multiply rather than add, but each distinct *unit id* only contributes
	once at its strongest — otherwise stacking six copies of one support trivially
	beats any real board.
]]
function StatMath.combineAuras(auras: { { unitId: Units.UnitId, aura: Units.Aura } }): AuraTotals
	local strongest: { [Units.UnitId]: Units.Aura } = {}
	for _, entry in auras do
		local current = strongest[entry.unitId]
		if not current or (entry.aura.Damage or 1) > (current.Damage or 1) then
			strongest[entry.unitId] = entry.aura
		end
	end

	local totals: AuraTotals = { Damage = 1, AttackSpeed = 1, Range = 1, Cash = 1 }
	for _, aura in strongest do
		totals.Damage *= aura.Damage or 1
		totals.AttackSpeed *= aura.AttackSpeed or 1
		totals.Range *= aura.Range or 1
		totals.Cash *= aura.Cash or 1
	end
	return totals
end

--[[
	Full stat line for one owned unit.

	`auras` is optional; pass nil for the "card" view (inventory, index, shop)
	and the live aura totals for the "on board" view.
]]
function StatMath.compute(
	unitId: Units.UnitId,
	level: number,
	traitId: Traits.TraitId?,
	mutationId: Mutations.MutationId?,
	auras: AuraTotals?
): ComputedStats
	local unit = Units.expect(unitId)
	local trait = Traits.get(traitId)
	local mutation = Mutations.get(mutationId)
	local aura = auras or StatMath.NoAura
	local mods = trait.Mods

	local levelMult = StatMath.levelMultiplier(level)

	local damage = unit.Damage * levelMult * mutation.Damage * (mods.Damage or 1) * aura.Damage
	local health = unit.Health * levelMult * mutation.Health * (mods.Health or 1)
	local attackSpeed = unit.AttackSpeed * (mods.AttackSpeed or 1) * aura.AttackSpeed
	local range = unit.Range * (mods.Range or 1) * aura.Range

	local critChance = math.clamp(unit.CritChance + (mods.CritChance or 0), 0, 1)
	local critDamage = unit.CritDamage + (mods.CritDamage or 0)

	local cash = mutation.Cash * (mods.Cash or 1) * aura.Cash
	local summons = math.max(1, mods.Summons or 1)

	return {
		Damage = damage,
		Health = health,
		AttackSpeed = attackSpeed,
		Range = range,
		CritChance = critChance,
		CritDamage = critDamage,
		CashMultiplier = cash,
		Summons = summons,
		Cooldown = 1 / math.max(attackSpeed, 0.01),
	}
end

--[[
	A single comparable number for a unit, used by "Equip Best" and by inventory
	sorting. Weighs sustained DPS most heavily, with a nod to reach and to the
	board value of tanks and supports.
]]
function StatMath.power(
	unitId: Units.UnitId,
	level: number,
	traitId: Traits.TraitId?,
	mutationId: Mutations.MutationId?
): number
	local unit = Units.expect(unitId)
	local stats = StatMath.compute(unitId, level, traitId, mutationId, nil)

	-- Expected damage per second including crits.
	local dps = stats.Damage * stats.AttackSpeed * (1 + stats.CritChance * (stats.CritDamage - 1))

	-- Area shapes hit more than one target; value them accordingly.
	local shapeMultiplier = 1
	if unit.AttackShape == "Splash" then
		shapeMultiplier = 1.8
	elseif unit.AttackShape == "Line" then
		shapeMultiplier = 2.2
	elseif unit.AttackShape == "Circle" then
		shapeMultiplier = 3.0
	elseif unit.AttackShape == "Full" then
		shapeMultiplier = 4.5
	end

	local score = dps * shapeMultiplier * (1 + stats.Range / 200)

	-- Tanks contribute integrity, supports contribute everyone else's damage.
	score += stats.Health * 0.35
	if unit.Aura then
		local auraValue = (unit.Aura.Damage or 1) * (unit.Aura.AttackSpeed or 1) * (unit.Aura.Cash or 1)
		score *= 1 + (auraValue - 1) * 1.5
	end

	return score
end

-- Gold awarded for a kill, after every multiplier the player owns.
function StatMath.killReward(bounty: number, unitCash: number, rarityMultiplier: number, playerGold: number): number
	return math.max(1, math.floor(bounty * unitCash * rarityMultiplier * playerGold + 0.5))
end

return StatMath
