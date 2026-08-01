--!strict
--[[
	Waves.luau

	Enemy archetypes and the procedural wave table.

	Waves are generated rather than hand-authored so the run can go on forever
	(the reference's leaderboard tops out around wave 199). The generator is pure
	and deterministic given a wave number, so the client can preview an upcoming
	wave without asking the server.
]]

local GameConfig = require(script.Parent.GameConfig)

export type EnemyId = string

export type Enemy = {
	Id: EnemyId,
	Display: string,
	-- Base stats at wave 1; the generator scales these.
	Health: number,
	Speed: number, -- studs/second along the track
	Bounty: number, -- gold on death, before player multipliers
	Damage: number, -- integrity removed if it reaches the core
	Color: Color3,
	Size: number,
	-- Optional behaviours.
	Armored: boolean?, -- takes reduced damage from Splash/Circle shapes
	Flying: boolean?, -- ignores ground-only units (none yet, reserved)
	Boss: boolean?,
	-- Earliest wave this archetype may appear on.
	MinWave: number,
}

local Waves = {}

Waves.Enemies = {
	Husk = {
		Id = "Husk",
		Display = "Husk",
		Health = 55,
		Speed = 9,
		Bounty = 28,
		Damage = 10,
		Color = Color3.fromRGB(150, 150, 160),
		Size = 3.4,
		MinWave = 1,
	},
	Skitter = {
		Id = "Skitter",
		Display = "Skitter",
		Health = 34,
		Speed = 16,
		Bounty = 24,
		Damage = 6,
		Color = Color3.fromRGB(196, 140, 90),
		Size = 2.6,
		MinWave = 3,
	},
	Bulwark = {
		Id = "Bulwark",
		Display = "Bulwark",
		Health = 210,
		Speed = 6,
		Bounty = 70,
		Damage = 25,
		Color = Color3.fromRGB(110, 122, 140),
		Size = 4.6,
		Armored = true,
		MinWave = 8,
	},
	Wraith = {
		Id = "Wraith",
		Display = "Wraith",
		Health = 130,
		Speed = 13,
		Bounty = 62,
		Damage = 18,
		Color = Color3.fromRGB(120, 96, 176),
		Size = 3.6,
		MinWave = 12,
	},
	Emberling = {
		Id = "Emberling",
		Display = "Emberling",
		Health = 96,
		Speed = 11,
		Bounty = 54,
		Damage = 14,
		Color = Color3.fromRGB(226, 118, 74),
		Size = 3.2,
		MinWave = 6,
	},
	Colossus = {
		Id = "Colossus",
		Display = "Colossus",
		Health = 900,
		Speed = 4.5,
		Bounty = 240,
		Damage = 60,
		Color = Color3.fromRGB(88, 100, 92),
		Size = 6.5,
		Armored = true,
		MinWave = 20,
	},
	Nullborn = {
		Id = "Nullborn",
		Display = "Nullborn",
		Health = 640,
		Speed = 14,
		Bounty = 190,
		Damage = 40,
		Color = Color3.fromRGB(108, 64, 190),
		Size = 4.0,
		MinWave = 30,
	},

	-- Bosses. One spawns on every BossInterval wave.
	WardenOfAsh = {
		Id = "WardenOfAsh",
		Display = "Warden of Ash",
		Health = 3200,
		Speed = 5,
		Bounty = 1400,
		Damage = 200,
		Color = Color3.fromRGB(210, 96, 60),
		Size = 9,
		Armored = true,
		Boss = true,
		MinWave = 10,
	},
	TheSilentTide = {
		Id = "TheSilentTide",
		Display = "The Silent Tide",
		Health = 5400,
		Speed = 7,
		Bounty = 2600,
		Damage = 260,
		Color = Color3.fromRGB(70, 150, 190),
		Size = 9.5,
		Boss = true,
		MinWave = 30,
	},
	CrownOfNothing = {
		Id = "CrownOfNothing",
		Display = "Crown of Nothing",
		Health = 9800,
		Speed = 6,
		Bounty = 5200,
		Damage = 400,
		Color = Color3.fromRGB(150, 80, 220),
		Size = 11,
		Armored = true,
		Boss = true,
		MinWave = 60,
	},
} :: { [EnemyId]: Enemy }

Waves.BossInterval = 10
Waves.BossRotation = { "WardenOfAsh", "TheSilentTide", "CrownOfNothing" } :: { EnemyId }

-- Damage multiplier applied to Armored enemies hit by area shapes.
Waves.ArmoredAreaResist = 0.55

export type WaveEntry = {
	EnemyId: EnemyId,
	Count: number,
	HealthMultiplier: number,
	BountyMultiplier: number,
}

export type WaveSpec = {
	Wave: number,
	Entries: { WaveEntry },
	TotalEnemies: number,
	IsBossWave: boolean,
	ClearBonus: number,
}

function Waves.get(id: EnemyId): Enemy
	local enemy = Waves.Enemies[id]
	assert(enemy, `Waves.get: unknown enemy "{tostring(id)}"`)
	return enemy
end

--[[
	Health scaling. Deliberately super-linear so that raw stat stacking stops
	working around wave 40 and the player has to start levelling and evolving
	units instead of placing more of them.
]]
local function healthScale(wave: number): number
	return 1 + (wave - 1) * 0.42 + (wave - 1) ^ 1.72 * 0.028
end

-- Bounty grows more slowly than health; that gap is the difficulty.
local function bountyScale(wave: number): number
	return 1 + (wave - 1) * 0.16 + (wave - 1) ^ 1.22 * 0.010
end

local function eligible(wave: number): { EnemyId }
	local list: { EnemyId } = {}
	for id, enemy in Waves.Enemies do
		if not enemy.Boss and wave >= enemy.MinWave then
			table.insert(list, id)
		end
	end
	table.sort(list)
	return list
end

--[[
	Deterministic per-wave composition. Same wave number always yields the same
	spec, on server and client alike.
]]
function Waves.spec(wave: number): WaveSpec
	assert(wave >= 1, "Waves.spec: wave must be >= 1")

	local isBoss = wave % Waves.BossInterval == 0
	local hp = healthScale(wave)
	local bounty = bountyScale(wave)

	local entries: { WaveEntry } = {}
	local total = 0

	local pool = eligible(wave)
	-- Composition width grows slowly: 1 archetype early, up to 4 late.
	local variety = math.clamp(1 + math.floor(wave / 9), 1, math.min(4, #pool))
	-- A fixed-seed generator keeps this pure without touching global RNG state.
	local rng = Random.new(wave * 7919 + 104729)

	-- Draw `variety` distinct archetypes, biased toward the newest unlocks.
	local chosen: { EnemyId } = {}
	local available = table.clone(pool)
	for _ = 1, variety do
		if #available == 0 then
			break
		end
		local index = rng:NextInteger(1, #available)
		table.insert(chosen, table.remove(available, index) :: EnemyId)
	end

	local budget = 4 + math.floor(wave * 0.75) + math.floor(wave ^ 1.15 * 0.10)
	if isBoss then
		-- Bosses replace part of the trash budget so boss waves are not just
		-- "the same wave plus a boss".
		budget = math.floor(budget * 0.55)
	end

	for i, enemyId in chosen do
		local share = if i == #chosen then 1 else rng:NextNumber(0.28, 0.5)
		local count = math.max(1, math.floor(budget * share + 0.5))
		budget -= count
		total += count
		table.insert(entries, {
			EnemyId = enemyId,
			Count = count,
			HealthMultiplier = hp,
			BountyMultiplier = bounty,
		})
		if budget <= 0 then
			break
		end
	end

	if isBoss then
		local rotationIndex = (wave // Waves.BossInterval - 1) % #Waves.BossRotation + 1
		local bossId = Waves.BossRotation[rotationIndex]
		-- Fall back to the strongest unlocked boss if the rotation outruns MinWave.
		local boss = Waves.get(bossId)
		if wave < boss.MinWave then
			bossId = "WardenOfAsh"
		end
		local bossCount = 1 + math.floor(wave / 50)
		total += bossCount
		table.insert(entries, {
			EnemyId = bossId,
			Count = bossCount,
			HealthMultiplier = hp * 1.15,
			BountyMultiplier = bounty,
		})
	end

	local clearBonus =
		math.floor(GameConfig.Economy.WaveClearBase * GameConfig.Economy.WaveClearGrowth ^ (wave - 1) + 0.5)

	return {
		Wave = wave,
		Entries = entries,
		TotalEnemies = total,
		IsBossWave = isBoss,
		ClearBonus = clearBonus,
	}
end

-- Scaled stats for one enemy instance on a given wave.
function Waves.statsFor(enemyId: EnemyId, entry: WaveEntry): (number, number, number)
	local enemy = Waves.get(enemyId)
	local health = math.floor(enemy.Health * entry.HealthMultiplier + 0.5)
	local bounty = math.floor(enemy.Bounty * entry.BountyMultiplier + 0.5)
	return health, bounty, enemy.Damage
end

return Waves
