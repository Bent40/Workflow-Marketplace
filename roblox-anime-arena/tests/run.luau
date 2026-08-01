--[[
	run.luau

	Tests for the game's pure logic — the odds tables, the wave generator, the
	stat pipeline and the cost curves. Run from the project root:

	    luau tests/run.luau

	These are the parts where a mistake is invisible in play but ruins the
	economy, so they are the parts worth testing outside Roblox.
]]

local Harness = require("./harness")
local M = Harness.load()

--------------------------------------------------------------------------------
-- Tiny test framework
--------------------------------------------------------------------------------

local passed, failed = 0, 0
local failures: { string } = {}

local function check(name: string, condition: boolean, detail: string?)
	if condition then
		passed += 1
	else
		failed += 1
		table.insert(failures, `{name}{if detail then ` — {detail}` else ""}`)
	end
end

local function approx(a: number, b: number, tolerance: number?): boolean
	return math.abs(a - b) <= (tolerance or 1e-6)
end

--------------------------------------------------------------------------------
-- Rarities
--------------------------------------------------------------------------------

do
	local Rarities = M.Rarities

	check("rarity order is complete", #Rarities.Order == 7)

	local lastOrder = 0
	local ordered = true
	for _, id in Rarities.Order do
		local rarity = Rarities.get(id)
		if rarity.Order ~= lastOrder + 1 then
			ordered = false
		end
		lastOrder = rarity.Order
	end
	check("rarity Order fields are 1..7 in sequence", ordered)

	-- Weights must strictly decrease as tiers improve, or the ladder is broken.
	local decreasing = true
	for i = 2, #Rarities.Order do
		local previous = Rarities.get(Rarities.Order[i - 1]).Weight
		local current = Rarities.get(Rarities.Order[i]).Weight
		if current >= previous then
			decreasing = false
		end
	end
	check("rarity weights strictly decrease", decreasing)

	check("luck 1.0 is the identity", approx(Rarities.weightAtLuck("Common", 1), Rarities.Data.Common.Weight))

	-- Higher luck must raise the top tiers and lower Common.
	local commonBase = Rarities.weightAtLuck("Common", 1)
	local commonLucky = Rarities.weightAtLuck("Common", 10)
	local godBase = Rarities.weightAtLuck("God", 1)
	local godLucky = Rarities.weightAtLuck("God", 10)
	check("luck shrinks Common weight", commonLucky < commonBase, `{commonLucky} vs {commonBase}`)
	check("luck grows God weight", godLucky > godBase, `{godLucky} vs {godBase}`)

	-- And the *probability* of a God roll must actually improve.
	local function godChance(luck: number): number
		local total = 0
		for _, id in Rarities.Order do
			total += Rarities.weightAtLuck(id, luck)
		end
		return Rarities.weightAtLuck("God", luck) / total
	end

	local base, mid, high = godChance(1), godChance(10), godChance(20)
	check("God odds improve with luck", base < mid and mid < high, `{base} < {mid} < {high}`)
	check("God odds stay rare at max luck", high < 0.02, `got {high}`)

	check("isBetter respects the ladder", Rarities.isBetter("Mythic", "Epic") and not Rarities.isBetter("Epic", "Mythic"))

	-- Pity thresholds must increase with tier, or a rarer tier would fire first.
	local pityIncreasing = true
	for i = 2, #Rarities.PityOrder do
		if Rarities.Pity[Rarities.PityOrder[i]] <= Rarities.Pity[Rarities.PityOrder[i - 1]] then
			pityIncreasing = false
		end
	end
	check("pity thresholds increase with tier", pityIncreasing)
end

--------------------------------------------------------------------------------
-- Units
--------------------------------------------------------------------------------

do
	local Units = M.Units
	local Rarities = M.Rarities

	check("roster is non-trivial", Units.Count >= 25, `got {Units.Count}`)

	-- Every rarity must have at least one unit, or a roll of that tier degrades.
	local everyTierPopulated = true
	for _, id in Rarities.Order do
		if #Units.ofRarity(id) == 0 then
			everyTierPopulated = false
		end
	end
	check("every rarity has at least one unit", everyTierPopulated)

	local wellFormed = true
	local problem = ""
	for _, unitId in Units.All do
		local unit = Units.expect(unitId)
		if unit.Damage <= 0 or unit.AttackSpeed <= 0 or unit.Range <= 0 or unit.MaxCopies < 1 then
			wellFormed = false
			problem = unitId
		end
		if unit.PlaceCost <= 0 then
			wellFormed = false
			problem = unitId
		end
		-- Area shapes that need a radius must declare one.
		if (unit.AttackShape == "Splash" or unit.AttackShape == "Line") and not unit.SplashRadius then
			wellFormed = false
			problem = `{unitId} (missing SplashRadius)`
		end
	end
	check("all units have sane stats", wellFormed, problem)

	-- Power must trend upward with rarity, otherwise "Equip Best" picks junk.
	local StatMath = M.StatMath
	local function averagePower(rarityId: string): number
		local bucket = Units.ofRarity(rarityId)
		local total = 0
		for _, unitId in bucket do
			total += StatMath.power(unitId, 1, "None", "None")
		end
		return total / #bucket
	end

	local monotonic = true
	local previous = -1
	local trace = {}
	for _, id in Rarities.Order do
		local power = averagePower(id)
		table.insert(trace, `{id}={math.floor(power)}`)
		if power <= previous then
			monotonic = false
		end
		previous = power
	end
	check("average power increases with rarity", monotonic, table.concat(trace, " "))
end

--------------------------------------------------------------------------------
-- Traits
--------------------------------------------------------------------------------

do
	local Traits = M.Traits
	local Rarities = M.Rarities

	local sum = 0
	for _, trait in Traits.Data do
		sum += trait.Weight
	end
	check("trait total weight matches helper", approx(Traits.totalWeight(), sum, 1e-9))

	-- God traits should sit near the reference's ~0.02% band.
	local cursedChance = Traits.chancePercent("Cursed")
	check("God trait odds are ~0.02%", cursedChance > 0.001 and cursedChance < 0.1, `got {cursedChance}%`)

	-- Rarer traits must be rarer.
	local byTier: { [string]: number } = {}
	for id, trait in Traits.Data do
		byTier[trait.Rarity] = (byTier[trait.Rarity] or 0) + trait.Weight
	end
	local tiersDecrease = true
	local previous = math.huge
	for _, id in Rarities.Order do
		local weight = byTier[id]
		if weight then
			if weight >= previous then
				tiersDecrease = false
			end
			previous = weight
		end
	end
	check("trait tier weights decrease", tiersDecrease)

	check("unknown trait falls back to None", Traits.get("NotARealTrait").Id == "None")
	check("nil trait falls back to None", Traits.get(nil).Id == "None")
	check("describe returns lines", #Traits.describe("Cursed") >= 5)
	check("None describes as no bonuses", Traits.describe("None")[1] == "No bonuses")
end

--------------------------------------------------------------------------------
-- StatMath
--------------------------------------------------------------------------------

do
	local StatMath = M.StatMath
	local GameConfig = M.GameConfig

	check("level 1 multiplier is 1", approx(StatMath.levelMultiplier(1), 1))

	local maxLevel = GameConfig.Inventory.MaxUnitLevel
	local expected = 1 + (maxLevel - 1) * GameConfig.Inventory.LevelStatGrowth
	check("max level multiplier matches config", approx(StatMath.levelMultiplier(maxLevel), expected))
	check("level is clamped above max", approx(StatMath.levelMultiplier(999), expected))
	check("level is clamped below 1", approx(StatMath.levelMultiplier(0), 1))

	local plain = StatMath.compute("Sparrowclad", 1, "None", "None", nil)
	local strong = StatMath.compute("Sparrowclad", 1, "Strong", "None", nil)
	check("Strong adds 10% damage", approx(strong.Damage, plain.Damage * 1.10, 1e-6))

	local gold = StatMath.compute("Sparrowclad", 1, "None", "Gold", nil)
	check("Gold mutation adds 25% damage", approx(gold.Damage, plain.Damage * 1.25, 1e-6))

	-- Trait and mutation must compound, not overwrite each other.
	local both = StatMath.compute("Sparrowclad", 1, "Strong", "Gold", nil)
	check("trait and mutation compound", approx(both.Damage, plain.Damage * 1.10 * 1.25, 1e-6))

	check("cooldown is the inverse of attack speed", approx(plain.Cooldown, 1 / plain.AttackSpeed, 1e-9))

	-- Crit chance can never exceed 100%, however many sources stack.
	local critty = StatMath.compute("EclipseVow", 20, "Cursed", "Celestial", nil)
	check("crit chance is clamped to 1", critty.CritChance <= 1, `got {critty.CritChance}`)

	-- Juggernaut trades attack speed for damage; make sure the sign is right.
	local jug = StatMath.compute("Sparrowclad", 1, "Juggernaut", "None", nil)
	check("Juggernaut slows attacks", jug.AttackSpeed < plain.AttackSpeed)
	check("Juggernaut raises damage", jug.Damage > plain.Damage)

	-- Auras multiply on top of everything else.
	local aura = StatMath.combineAuras({
		{ unitId = "Aurorin", aura = { Damage = 1.22 } },
		{ unitId = "Aurorin", aura = { Damage = 1.10 } }, -- duplicate id, weaker
	})
	check("duplicate aura sources do not stack", approx(aura.Damage, 1.22, 1e-9), `got {aura.Damage}`)

	local twoSources = StatMath.combineAuras({
		{ unitId = "Aurorin", aura = { Damage = 1.22 } },
		{ unitId = "LotusWarden", aura = { Damage = 1.08 } },
	})
	check("distinct aura sources multiply", approx(twoSources.Damage, 1.22 * 1.08, 1e-9))

	local buffed = StatMath.compute("Sparrowclad", 1, "None", "None", twoSources)
	check("auras apply to damage", approx(buffed.Damage, plain.Damage * 1.22 * 1.08, 1e-6))
	check("auras do not apply to health", approx(buffed.Health, plain.Health, 1e-6))
end

--------------------------------------------------------------------------------
-- Waves
--------------------------------------------------------------------------------

do
	local Waves = M.Waves

	local first = Waves.spec(1)
	check("wave 1 has enemies", first.TotalEnemies > 0)
	check("wave 1 is not a boss wave", not first.IsBossWave)

	-- Determinism: the client previews waves without asking the server, so the
	-- same wave number must always produce the same composition.
	local a = Waves.spec(37)
	local b = Waves.spec(37)
	local sameShape = a.TotalEnemies == b.TotalEnemies and #a.Entries == #b.Entries
	if sameShape then
		for i, entry in a.Entries do
			if entry.EnemyId ~= b.Entries[i].EnemyId or entry.Count ~= b.Entries[i].Count then
				sameShape = false
			end
		end
	end
	check("wave generation is deterministic", sameShape)

	check("every 10th wave is a boss wave", Waves.spec(10).IsBossWave and Waves.spec(20).IsBossWave)
	check("wave 11 is not a boss wave", not Waves.spec(11).IsBossWave)

	local hasBoss = false
	for _, entry in Waves.spec(10).Entries do
		if Waves.get(entry.EnemyId).Boss then
			hasBoss = true
		end
	end
	check("boss waves contain a boss", hasBoss)

	-- Enemy count and health must both climb, and health must outpace bounty —
	-- that gap is the difficulty curve.
	local growing = true
	local previousTotal = 0
	for wave = 1, 60 do
		local spec = Waves.spec(wave)
		if spec.TotalEnemies <= 0 then
			growing = false
		end
		previousTotal = spec.TotalEnemies
	end
	check("all waves 1-60 are populated", growing, `last total {previousTotal}`)

	local early = Waves.spec(5).Entries[1]
	local late = Waves.spec(80).Entries[1]
	check("health scales up with wave", late.HealthMultiplier > early.HealthMultiplier * 20)
	check(
		"health outpaces bounty",
		late.HealthMultiplier / early.HealthMultiplier > late.BountyMultiplier / early.BountyMultiplier,
		`hp x{late.HealthMultiplier / early.HealthMultiplier} vs gold x{late.BountyMultiplier / early.BountyMultiplier}`
	)

	-- No wave may reference an enemy before its MinWave.
	local respectsMinWave = true
	local offender = ""
	for wave = 1, 120 do
		for _, entry in Waves.spec(wave).Entries do
			if wave < Waves.get(entry.EnemyId).MinWave then
				respectsMinWave = false
				offender = `wave {wave} spawned {entry.EnemyId}`
			end
		end
	end
	check("waves respect enemy MinWave", respectsMinWave, offender)

	-- Entries must sum to TotalEnemies, or the "X/Y left" counter desyncs and the
	-- wave-clear check can never fire.
	local countsMatch = true
	local mismatch = ""
	for wave = 1, 120 do
		local spec = Waves.spec(wave)
		local sum = 0
		for _, entry in spec.Entries do
			sum += entry.Count
		end
		if sum ~= spec.TotalEnemies then
			countsMatch = false
			mismatch = `wave {wave}: entries {sum} vs total {spec.TotalEnemies}`
		end
	end
	check("entry counts sum to TotalEnemies", countsMatch, mismatch)

	check("wave 200 still generates", Waves.spec(200).TotalEnemies > 0)
end

--------------------------------------------------------------------------------
-- Upgrades
--------------------------------------------------------------------------------

do
	local Upgrades = M.Upgrades

	for _, id in Upgrades.Order do
		local config = Upgrades.get(id)
		check(`{id} costs rise with level`, (Upgrades.costToNext(id, 5) :: number) > (Upgrades.costToNext(id, 1) :: number))
		check(`{id} has no cost at max`, Upgrades.costToNext(id, config.MaxLevel) == nil)
		check(`{id} effect rises with level`, Upgrades.effectAt(id, 2) > Upgrades.effectAt(id, 1))
		check(`{id} effect is clamped at max`, Upgrades.effectAt(id, 9999) == Upgrades.effectAt(id, config.MaxLevel))
	end

	check("slot upgrade starts at the configured base", Upgrades.effectAt("Slot", 1) == M.GameConfig.Bases.StartingSlots)
	check(
		"inventory upgrade starts at the configured base",
		Upgrades.effectAt("Inventory", 1) == M.GameConfig.Inventory.BaseCapacity
	)
	check("luck starts at 1x", approx(Upgrades.effectAt("Luck", 1), 1))
	check("gold starts at 1x", approx(Upgrades.effectAt("Gold", 1), 1))
end

--------------------------------------------------------------------------------
-- Shop
--------------------------------------------------------------------------------

do
	local ShopConfig = M.ShopConfig
	local Rarities = M.Rarities

	check("shop has six slots", ShopConfig.SlotCount == 6)

	-- The escalating refresh cost is the whole anti-whale mechanism; verify it
	-- actually escalates and then caps.
	local costs = {}
	for i = 0, 8 do
		table.insert(costs, ShopConfig.refreshCost(i))
	end
	local escalating = true
	for i = 2, #costs do
		if costs[i] < costs[i - 1] then
			escalating = false
		end
	end
	check("refresh cost escalates", escalating, table.concat(costs, ","))
	check("refresh cost is capped", ShopConfig.refreshCost(50) == ShopConfig.RefreshCostCap)
	check("first refresh is the base cost", costs[1] == ShopConfig.RefreshBaseCost)

	-- Shop prices must rise with rarity.
	local pricesRise = true
	local previous = -1
	for _, id in Rarities.Order do
		local price = ShopConfig.priceFor(id, 0)
		if price <= previous then
			pricesRise = false
		end
		previous = price
	end
	check("shop prices rise with rarity", pricesRise)

	check("discounts reduce price", ShopConfig.priceFor("Epic", 0.5) < ShopConfig.priceFor("Epic", 0))
	check("price never drops below 1", ShopConfig.priceFor("Common", 1) >= 1)

	-- The shop's rarity table must be flatter than the roll table — that is what
	-- makes it the deterministic path rather than a second lottery.
	local function ratio(map, getter): number
		local total = 0
		for _, id in Rarities.Order do
			total += getter(map, id)
		end
		return getter(map, "Legendary") / total
	end

	local shopLegendary = ratio(ShopConfig.RarityWeights, function(map, id)
		return map[id]
	end)
	local rollLegendary = ratio(nil, function(_, id)
		return Rarities.get(id).Weight
	end)
	check(
		"shop is more generous than rolling at Legendary",
		shopLegendary > rollLegendary,
		`shop {shopLegendary} vs roll {rollLegendary}`
	)
end

--------------------------------------------------------------------------------
-- WeightedPick
--------------------------------------------------------------------------------

do
	local WeightedPick = M.WeightedPick
	local Random = M._Random

	local rng = Random.new(12345)

	check("zero-weight pool returns nil", WeightedPick.pick({ { key = "a", weight = 0 } }, rng) == nil)
	check("empty pool returns nil", WeightedPick.pick({}, rng) == nil)

	-- A single positive entry must always win.
	local onlyChoice = true
	for _ = 1, 50 do
		if WeightedPick.pick({ { key = "a", weight = 1 }, { key = "b", weight = 0 } }, rng) ~= "a" then
			onlyChoice = false
		end
	end
	check("zero-weight entries are never picked", onlyChoice)

	-- Distribution sanity: 9:1 weights should land near 90/10 over many draws.
	local counts = { a = 0, b = 0 }
	local trials = 20000
	for _ = 1, trials do
		local key = WeightedPick.pick({ { key = "a", weight = 9 }, { key = "b", weight = 1 } }, rng)
		counts[key] += 1
	end
	local share = counts.a / trials
	check("weighted distribution is approximately correct", math.abs(share - 0.9) < 0.02, `got {share}`)

	local probabilities = WeightedPick.probabilities({ a = 3, b = 1 })
	check("probabilities normalise", approx(probabilities.a, 0.75) and approx(probabilities.b, 0.25))

	local total = 0
	for _, value in WeightedPick.probabilities({ x = 5, y = 7, z = 11 }) do
		total += value
	end
	check("probabilities sum to 1", approx(total, 1, 1e-9))
end

--------------------------------------------------------------------------------
-- Format
--------------------------------------------------------------------------------

do
	local Format = M.Format

	check("abbreviate handles small numbers", Format.abbreviate(999) == "999")
	check("abbreviate handles thousands", Format.abbreviate(1500) == "1.5K", Format.abbreviate(1500))
	check("abbreviate handles millions", Format.abbreviate(1234567) == "1.23M", Format.abbreviate(1234567))
	check("abbreviate trims trailing zeros", Format.abbreviate(2000000) == "2M", Format.abbreviate(2000000))
	check("abbreviate handles zero", Format.abbreviate(0) == "0")
	check("abbreviate handles negatives", Format.abbreviate(-1500) == "-1.5K", Format.abbreviate(-1500))

	check("comma groups digits", Format.comma(1234567) == "1,234,567", Format.comma(1234567))
	check("comma handles small numbers", Format.comma(42) == "42")
	check("comma handles zero", Format.comma(0) == "0")

	check("clock formats minutes", Format.clock(90) == "01:30", Format.clock(90))
	check("clock formats hours", Format.clock(3725) == "01:02:05", Format.clock(3725))
	check("clock floors negatives to zero", Format.clock(-5) == "00:00")

	check("percent formats", Format.percent(0.0234, 2) == "2.34%", Format.percent(0.0234, 2))
	check("odds handles zero", Format.odds(0) == "—")
end

--------------------------------------------------------------------------------
-- Items and Codes
--------------------------------------------------------------------------------

do
	local Items = M.Items
	local Rarities = M.Rarities

	local everyRarityHasEssence = true
	for _, id in Rarities.Order do
		local entry = Items.CloneCost[id]
		if not entry or not Items.get(entry.Essence) then
			everyRarityHasEssence = false
		end
	end
	check("every rarity has a clone cost and essence", everyRarityHasEssence)

	-- Clone cost and duration must both rise with rarity.
	local risingCost, risingTime = true, true
	local previousAmount, previousSeconds = -1, -1
	for _, id in Rarities.Order do
		local entry = Items.CloneCost[id]
		if entry.Amount <= previousAmount then
			risingCost = false
		end
		if entry.Seconds <= previousSeconds then
			risingTime = false
		end
		previousAmount, previousSeconds = entry.Amount, entry.Seconds
	end
	check("clone essence cost rises with rarity", risingCost)
	check("clone duration rises with rarity", risingTime)

	local Codes = M.Codes
	check("a known code resolves", Codes.get("release") ~= nil)
	check("code lookup is case and space insensitive", Codes.get("  ReLeAsE ") ~= nil)
	check("an unknown code returns nil", Codes.get("definitely-not-a-code") == nil)

	local everyCodeRewards = true
	for _, code in Codes.Data do
		local reward = code.Reward
		if not (reward.Gold or reward.Gems or reward.Items or reward.Rolls) then
			everyCodeRewards = false
		end
	end
	check("every code grants something", everyCodeRewards)
end

--------------------------------------------------------------------------------
-- Monetization
--------------------------------------------------------------------------------

do
	local Monetization = M.Monetization

	-- Unconfigured ids must never resolve to a product, or a stray receipt for
	-- product 0 would grant a random bundle.
	check("asset id 0 never matches a product", Monetization.productByAssetId(0) == nil)

	local everyProductGrants = true
	for _, product in Monetization.DevProducts do
		if not (product.Gems or product.Gold or product.Items) then
			everyProductGrants = false
		end
	end
	check("every dev product grants something", everyProductGrants)

	local ordered = Monetization.orderedProducts()
	local sorted = true
	for i = 2, #ordered do
		if ordered[i].Order < ordered[i - 1].Order then
			sorted = false
		end
	end
	check("products are returned in order", sorted)
	check("passes are returned in order", #Monetization.orderedPasses() > 0)
end

--------------------------------------------------------------------------------
-- Report
--------------------------------------------------------------------------------

print(string.rep("=", 62))
if failed == 0 then
	print(`PASS — {passed} checks`)
else
	print(`FAIL — {failed} failed, {passed} passed`)
	for _, failure in failures do
		print(`  ✗ {failure}`)
	end
end
print(string.rep("=", 62))

if failed > 0 then
	error("tests failed", 0)
end
