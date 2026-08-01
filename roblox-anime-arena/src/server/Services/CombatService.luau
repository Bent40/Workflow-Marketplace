--!strict
--[[
	CombatService.luau

	The wave runner. One instance drives all eight bases.

	Two clocks
	----------
	Movement runs on Heartbeat so enemy parts replicate smoothly. Targeting and
	damage run on a fixed 10Hz tick (GameConfig.Combat.TickRate), because
	resolving every unit against every enemy each frame is what actually costs
	server time, and 10Hz is imperceptible for tower-defense pacing.

	Everything here is server-authoritative. The client is told what spawned, what
	took damage and what died; it never decides any of it.
]]

local RunService = game:GetService("RunService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Items = require(Shared.Config.Items)
local Net = require(Shared.Net)
local Rarities = require(Shared.Config.Rarities)
local Units = require(Shared.Config.Units)
local Waves = require(Shared.Config.Waves)
local StatMath = require(Shared.Util.StatMath)
local WeightedPick = require(Shared.Util.WeightedPick)
local Types = require(Shared.Types)

local BaseService = require(script.Parent.BaseService)
local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local SyncService = require(script.Parent.SyncService)

type BaseState = BaseService.BaseState

local CombatService = {}

local rng = Random.new()

export type Enemy = {
	Key: number,
	EnemyId: string,
	Health: number,
	MaxHealth: number,
	Speed: number,
	Bounty: number,
	CoreDamage: number,
	Armored: boolean,
	IsBoss: boolean,
	-- Distance travelled along the track, in studs.
	Distance: number,
	Part: BasePart,
	Alive: boolean,
}

type Run = {
	Base: BaseState,
	Enemies: { [number]: Enemy },
	LiveCount: number,
	-- Enemies still to spawn this wave, flattened from the wave spec.
	SpawnQueue: { { EnemyId: string, Health: number, Bounty: number } },
	SpawnTimer: number,
	TotalThisWave: number,
	RemainingThisWave: number,
	NextKey: number,
	InterWaveTimer: number,
	-- Cached aura totals, recomputed whenever the board changes.
	Auras: StatMath.AuraTotals,
	AurasDirty: boolean,
}

local runs: { [number]: Run } = {}
local accumulator = 0

--------------------------------------------------------------------------------
-- Track helpers
--------------------------------------------------------------------------------

--[[
	World position at `distance` studs along the plot's track. Returns the
	position and whether the enemy has reached the end.
]]
local function trackPosition(waypoints: { Vector3 }, distance: number): (Vector3, boolean)
	local travelled = 0
	for i = 1, #waypoints - 1 do
		local a = waypoints[i]
		local b = waypoints[i + 1]
		local segmentLength = (b - a).Magnitude
		if travelled + segmentLength >= distance then
			local t = if segmentLength > 0 then (distance - travelled) / segmentLength else 0
			return a:Lerp(b, t), false
		end
		travelled += segmentLength
	end
	return waypoints[#waypoints], true
end

--------------------------------------------------------------------------------
-- Aura aggregation
--------------------------------------------------------------------------------

--[[
	Support auras are global to the base rather than positional.

	A positional aura would be more interesting, but it makes "where do I put the
	support" the only real decision on the board and turns every optimal layout
	into the same clump. Global auras keep placement about coverage of the track.
]]
local function computeAuras(state: BaseState): StatMath.AuraTotals
	local profile = if state.Owner then DataService.get(state.Owner) else nil
	if not profile then
		return StatMath.NoAura
	end

	local contributions: { { unitId: string, aura: Units.Aura } } = {}
	for uid, record in state.Placed do
		local unit = Units.get(record.UnitId)
		local owned = profile.Inventory[uid]
		if unit and unit.Aura and owned then
			-- Aura strength scales with the support's level, like everything else.
			local levelMult = StatMath.levelMultiplier(owned.Level)
			local scaled: Units.Aura = {
				Damage = if unit.Aura.Damage then 1 + (unit.Aura.Damage - 1) * levelMult else nil,
				AttackSpeed = if unit.Aura.AttackSpeed
					then 1 + (unit.Aura.AttackSpeed - 1) * levelMult
					else nil,
				Range = unit.Aura.Range,
				Cash = unit.Aura.Cash,
			}
			table.insert(contributions, { unitId = record.UnitId, aura = scaled })
		end
	end

	return StatMath.combineAuras(contributions)
end

function CombatService.markAurasDirty(baseIndex: number)
	local run = runs[baseIndex]
	if run then
		run.AurasDirty = true
	end
end

--------------------------------------------------------------------------------
-- Enemy lifecycle
--------------------------------------------------------------------------------

local function buildEnemyPart(enemyId: string, position: Vector3, parent: Instance): BasePart
	local config = Waves.get(enemyId)

	local part = Instance.new("Part")
	part.Name = enemyId
	part.Size = Vector3.new(config.Size, config.Size, config.Size)
	part.Shape = if config.Boss then Enum.PartType.Block else Enum.PartType.Ball
	part.Position = position + Vector3.new(0, config.Size / 2, 0)
	part.Anchored = true
	part.CanCollide = false
	part.CanQuery = false
	part.CanTouch = false
	part.Material = if config.Boss then Enum.Material.Neon else Enum.Material.SmoothPlastic
	part.Color = config.Color
	part.Parent = parent

	local billboard = Instance.new("BillboardGui")
	billboard.Name = "HealthBar"
	billboard.Size = UDim2.fromScale(6, 0.7)
	billboard.StudsOffsetWorldSpace = Vector3.new(0, config.Size * 0.8, 0)
	billboard.MaxDistance = 260
	billboard.Parent = part

	local background = Instance.new("Frame")
	background.Name = "Bar"
	background.Size = UDim2.fromScale(1, 1)
	background.BackgroundColor3 = Color3.fromRGB(20, 20, 26)
	background.BorderSizePixel = 0
	background.Parent = billboard

	local fill = Instance.new("Frame")
	fill.Name = "Fill"
	fill.Size = UDim2.fromScale(1, 1)
	fill.BackgroundColor3 = if config.Boss then Color3.fromRGB(255, 90, 120) else Color3.fromRGB(120, 230, 130)
	fill.BorderSizePixel = 0
	fill.Parent = background

	return part
end

local function spawnEnemy(run: Run, entry: { EnemyId: string, Health: number, Bounty: number })
	local config = Waves.get(entry.EnemyId)
	local plot = run.Base.Plot

	local position = trackPosition(plot.Waypoints, 0)
	local part = buildEnemyPart(entry.EnemyId, position, plot.EnemyFolder)

	local key = run.NextKey
	run.NextKey += 1

	local enemy: Enemy = {
		Key = key,
		EnemyId = entry.EnemyId,
		Health = entry.Health,
		MaxHealth = entry.Health,
		Speed = config.Speed,
		Bounty = entry.Bounty,
		CoreDamage = config.Damage,
		Armored = config.Armored == true,
		IsBoss = config.Boss == true,
		Distance = 0,
		Part = part,
		Alive = true,
	}

	run.Enemies[key] = enemy
	run.LiveCount += 1

	Net.event("EnemySpawned"):FireAllClients(run.Base.Index, key, entry.EnemyId, entry.Health)
end

local function despawn(run: Run, enemy: Enemy)
	if not enemy.Alive then
		return
	end
	enemy.Alive = false
	run.Enemies[enemy.Key] = nil
	run.LiveCount = math.max(0, run.LiveCount - 1)
	if enemy.Part.Parent then
		enemy.Part:Destroy()
	end
end

--------------------------------------------------------------------------------
-- Drops
--------------------------------------------------------------------------------

local function rollDrops(player: Player, profile: Types.Profile, isBoss: boolean)
	local essenceChance = Items.EssenceDropChance * (if isBoss then 5 else 1)
	if rng:NextNumber() < essenceChance then
		local rarity = WeightedPick.fromMap(Items.EssenceDropWeights, rng)
		if rarity then
			CurrencyService.addItem(player, profile, Items.essenceFor(rarity), if isBoss then 5 else 1)
		end
	end

	local shardChance = Items.TraitShardDropChance * (if isBoss then 8 else 1)
	if rng:NextNumber() < shardChance then
		CurrencyService.addItem(player, profile, "TraitShard", 1)
	end
end

--------------------------------------------------------------------------------
-- Wave control
--------------------------------------------------------------------------------

local function buildSpawnQueue(wave: number): ({ { EnemyId: string, Health: number, Bounty: number } }, number)
	local spec = Waves.spec(wave)
	local queue: { { EnemyId: string, Health: number, Bounty: number } } = {}

	for _, entry in spec.Entries do
		local health, bounty = Waves.statsFor(entry.EnemyId, entry)
		for _ = 1, entry.Count do
			table.insert(queue, { EnemyId = entry.EnemyId, Health = health, Bounty = bounty })
		end
	end

	-- Bosses are appended last by the spec; shuffle only the non-boss prefix so
	-- the boss still arrives at the end of the wave.
	local trashCount = #queue
	for _, entry in spec.Entries do
		if Waves.get(entry.EnemyId).Boss then
			trashCount -= entry.Count
		end
	end
	for i = trashCount, 2, -1 do
		local j = rng:NextInteger(1, i)
		queue[i], queue[j] = queue[j], queue[i]
	end

	return queue, spec.TotalEnemies
end

local function getRun(state: BaseState): Run
	local run = runs[state.Index]
	if run then
		run.Base = state
		return run
	end

	run = {
		Base = state,
		Enemies = {},
		LiveCount = 0,
		SpawnQueue = {},
		SpawnTimer = 0,
		TotalThisWave = 0,
		RemainingThisWave = 0,
		NextKey = 1,
		InterWaveTimer = 0,
		Auras = StatMath.NoAura,
		AurasDirty = true,
	}
	runs[state.Index] = run
	return run
end

local function beginWave(run: Run, wave: number)
	local queue, total = buildSpawnQueue(wave)
	run.SpawnQueue = queue
	run.SpawnTimer = 0
	run.TotalThisWave = total
	run.RemainingThisWave = total
	run.AurasDirty = true

	run.Base.Wave = wave
	run.Base.Running = true

	Net.event("WaveStarted"):FireAllClients(run.Base.Index, wave, total)
	BaseService.broadcast(run.Base, run.RemainingThisWave, run.TotalThisWave)
end

local function clearRunEnemies(run: Run)
	for _, enemy in run.Enemies do
		if enemy.Part.Parent then
			enemy.Part:Destroy()
		end
	end
	run.Enemies = {}
	run.LiveCount = 0
	run.SpawnQueue = {}
	run.RemainingThisWave = 0
end

function CombatService.startWave(player: Player): Types.Result<{ wave: number }>
	local state = BaseService.forPlayer(player)
	if not state then
		return { ok = false, err = "You don't have a base yet." }
	end
	if state.Running then
		return { ok = false, err = "A wave is already running." }
	end
	if state.PlacedCount == 0 then
		return { ok = false, err = "Place at least one unit before starting." }
	end

	local run = getRun(state)
	-- Restore the core before each attempt; integrity is per-wave, not per-run.
	state.Integrity = state.MaxIntegrity
	beginWave(run, state.Wave + 1)

	return { ok = true, data = { wave = state.Wave } }
end

function CombatService.stopWave(player: Player): Types.Result<nil>
	local state = BaseService.forPlayer(player)
	if not state then
		return { ok = false, err = "You don't have a base yet." }
	end

	local run = getRun(state)
	clearRunEnemies(run)
	state.Running = false
	state.AutoWave = false
	-- Stopping mid-wave forfeits the wave: the next start replays it.
	state.Wave = math.max(0, state.Wave - 1)

	BaseService.broadcast(state, 0, 0)
	return { ok = true }
end

function CombatService.setAutoWave(player: Player, enabled: boolean): Types.Result<{ enabled: boolean }>
	local state = BaseService.forPlayer(player)
	if not state then
		return { ok = false, err = "You don't have a base yet." }
	end
	state.AutoWave = enabled == true
	BaseService.broadcast(state)
	return { ok = true, data = { enabled = state.AutoWave } }
end

local function onWaveCleared(run: Run)
	local state = run.Base
	state.Running = false

	local player = state.Owner
	local profile = if player then DataService.get(player) else nil
	local spec = Waves.spec(state.Wave)

	if player and profile then
		local bonus = math.floor(spec.ClearBonus * CurrencyService.getGoldMultiplier(player, profile))
		CurrencyService.addGold(player, profile, bonus)

		if state.Wave > profile.Stats.HighestWave then
			profile.Stats.HighestWave = state.Wave
			DataService.markDirty(player)
		end

		SyncService.push(player)
		Net.event("WaveCleared"):FireAllClients(state.Index, state.Wave, bonus)
	end

	BaseService.broadcast(state, 0, 0)

	if state.AutoWave then
		run.InterWaveTimer = GameConfig.Combat.InterWaveDelay
	end
end

local function onBaseFell(run: Run)
	local state = run.Base
	clearRunEnemies(run)
	state.Running = false
	state.AutoWave = false

	Net.event("BaseFell"):FireAllClients(state.Index, state.Wave)

	if state.Owner then
		SyncService.toast(state.Owner, "error", `Your base fell on wave {state.Wave}. Rebuild and try again.`)
	end

	-- The run restarts from wave 1; placements and the collection are untouched,
	-- so a loss costs time, not progress.
	state.Wave = 0
	state.Integrity = state.MaxIntegrity
	BaseService.broadcast(state, 0, 0)
end

--------------------------------------------------------------------------------
-- Targeting
--------------------------------------------------------------------------------

-- Furthest-along-the-track first. Standard TD "first" targeting: it is the enemy
-- closest to ending the run, so it is the correct one to shoot.
local function findPrimaryTarget(run: Run, origin: Vector3, range: number): Enemy?
	local best: Enemy? = nil
	local bestDistance = -1

	for _, enemy in run.Enemies do
		if enemy.Alive and enemy.Distance > bestDistance then
			if (enemy.Part.Position - origin).Magnitude <= range then
				best = enemy
				bestDistance = enemy.Distance
			end
		end
	end

	return best
end

local function collectTargets(run: Run, unit: Units.Unit, origin: Vector3, range: number, primary: Enemy): { Enemy }
	local shape = unit.AttackShape

	if shape == "Single" then
		return { primary }
	end

	if shape == "Full" then
		local all: { Enemy } = {}
		for _, enemy in run.Enemies do
			if enemy.Alive then
				table.insert(all, enemy)
			end
		end
		return all
	end

	if shape == "Circle" then
		local inRange: { Enemy } = {}
		for _, enemy in run.Enemies do
			if enemy.Alive and (enemy.Part.Position - origin).Magnitude <= range then
				table.insert(inRange, enemy)
			end
		end
		return inRange
	end

	if shape == "Splash" then
		local radius = unit.SplashRadius or 6
		local hit: { Enemy } = { primary }
		for _, enemy in run.Enemies do
			if enemy.Alive and enemy ~= primary then
				if (enemy.Part.Position - primary.Part.Position).Magnitude <= radius then
					table.insert(hit, enemy)
				end
			end
		end
		return hit
	end

	if shape == "Line" then
		local width = unit.SplashRadius or 5
		local direction = (primary.Part.Position - origin)
		local length = direction.Magnitude
		if length < 0.01 then
			return { primary }
		end
		direction = direction.Unit

		local hit: { Enemy } = {}
		for _, enemy in run.Enemies do
			if enemy.Alive then
				local offset = enemy.Part.Position - origin
				local along = offset:Dot(direction)
				-- Pierce continues past the primary target to the edge of range.
				if along >= 0 and along <= range then
					local perpendicular = (offset - direction * along).Magnitude
					if perpendicular <= width then
						table.insert(hit, enemy)
					end
				end
			end
		end
		return hit
	end

	return { primary }
end

--------------------------------------------------------------------------------
-- Damage
--------------------------------------------------------------------------------

local function applyDamage(run: Run, enemy: Enemy, amount: number, isArea: boolean): boolean
	local damage = amount
	if enemy.Armored and isArea then
		damage *= Waves.ArmoredAreaResist
	end

	enemy.Health -= damage

	local billboard = enemy.Part:FindFirstChild("HealthBar")
	if billboard then
		local background = billboard:FindFirstChildWhichIsA("Frame")
		local fill = background and background:FindFirstChild("Fill")
		if fill and fill:IsA("Frame") then
			fill.Size = UDim2.fromScale(math.clamp(enemy.Health / enemy.MaxHealth, 0, 1), 1)
		end
	end

	if enemy.Health <= 0 then
		return true
	end

	Net.event("EnemyDamaged"):FireAllClients(run.Base.Index, enemy.Key, math.max(enemy.Health, 0))
	return false
end

local function killEnemy(run: Run, enemy: Enemy, cashMultiplier: number, rarityMultiplier: number)
	local state = run.Base
	local player = state.Owner
	local profile = if player then DataService.get(player) else nil

	local reward = 0
	if player and profile then
		local goldMultiplier = CurrencyService.getGoldMultiplier(player, profile)
		reward = StatMath.killReward(enemy.Bounty, cashMultiplier, rarityMultiplier, goldMultiplier)
		CurrencyService.addGold(player, profile, reward)
		profile.Stats.TotalKills += 1
		rollDrops(player, profile, enemy.IsBoss)
		SyncService.push(player)
	end

	Net.event("EnemyDied"):FireAllClients(state.Index, enemy.Key, reward)
	despawn(run, enemy)

	run.RemainingThisWave = math.max(0, run.RemainingThisWave - 1)
end

--------------------------------------------------------------------------------
-- Tick
--------------------------------------------------------------------------------

local function tickCombat(run: Run)
	local state = run.Base
	local player = state.Owner
	local profile = if player then DataService.get(player) else nil
	if not player or not profile then
		return
	end

	if run.AurasDirty then
		run.Auras = computeAuras(state)
		run.AurasDirty = false
	end

	local now = os.clock()

	for uid, record in state.Placed do
		local owned = profile.Inventory[uid]
		if not owned then
			continue
		end
		if now < record.NextAttack then
			continue
		end

		local unit = Units.expect(record.UnitId)
		local stats = StatMath.compute(record.UnitId, owned.Level, owned.Trait, owned.Mutation, run.Auras)
		local origin = record.Position + Vector3.new(0, 4, 0)

		local primary = findPrimaryTarget(run, origin, stats.Range)
		if not primary then
			continue
		end

		record.NextAttack = now + stats.Cooldown

		local isCrit = rng:NextNumber() < stats.CritChance
		local damage = stats.Damage * (if isCrit then stats.CritDamage else 1)
		-- The Cloner/Ascendant traits field extra bodies, which read as extra hits.
		damage *= stats.Summons

		local targets = collectTargets(run, unit, origin, stats.Range, primary)
		local isArea = unit.AttackShape ~= "Single"
		local rarityMultiplier = Rarities.get(unit.Rarity).BountyMultiplier

		-- Snapshot the keys before resolving damage: killEnemy despawns entries,
		-- and the client still wants to draw a tracer at everything that was hit.
		local targetKeys: { number } = {}
		for _, enemy in targets do
			table.insert(targetKeys, enemy.Key)
		end

		for _, enemy in targets do
			if enemy.Alive and applyDamage(run, enemy, damage, isArea) then
				killEnemy(run, enemy, stats.CashMultiplier, rarityMultiplier)
			end
		end

		Net.event("UnitFired"):FireAllClients(state.Index, uid, targetKeys, isCrit)
	end
end

local function tickMovement(run: Run, dt: number)
	local state = run.Base
	local plot = state.Plot
	local profile = if state.Owner then DataService.get(state.Owner) else nil

	local speedMultiplier = 1
	if profile and CurrencyService.hasFastForward(profile) then
		speedMultiplier = GameConfig.Combat.FastForwardMultiplier
	end

	local breached = 0

	for _, enemy in run.Enemies do
		if not enemy.Alive then
			continue
		end

		enemy.Distance += enemy.Speed * dt * speedMultiplier
		local position, atEnd = trackPosition(plot.Waypoints, enemy.Distance)

		if atEnd then
			breached += enemy.CoreDamage
			despawn(run, enemy)
			run.RemainingThisWave = math.max(0, run.RemainingThisWave - 1)
		else
			local size = enemy.Part.Size.Y
			enemy.Part.Position = position + Vector3.new(0, size / 2, 0)
		end
	end

	if breached > 0 then
		state.Integrity = math.max(0, state.Integrity - breached)
		BaseService.broadcast(state, run.RemainingThisWave, run.TotalThisWave)

		if state.Integrity <= 0 then
			onBaseFell(run)
		end
	end
end

local function tickSpawning(run: Run, dt: number)
	if #run.SpawnQueue == 0 then
		return
	end
	if run.LiveCount >= GameConfig.Combat.MaxLiveEnemies then
		return
	end

	local profile = if run.Base.Owner then DataService.get(run.Base.Owner) else nil
	local speedMultiplier = 1
	if profile and CurrencyService.hasFastForward(profile) then
		speedMultiplier = GameConfig.Combat.FastForwardMultiplier
	end

	run.SpawnTimer -= dt * speedMultiplier
	while run.SpawnTimer <= 0 and #run.SpawnQueue > 0 do
		spawnEnemy(run, table.remove(run.SpawnQueue, 1) :: any)
		run.SpawnTimer += GameConfig.Combat.SpawnInterval
	end
end

--------------------------------------------------------------------------------
-- Lifecycle
--------------------------------------------------------------------------------

function CombatService.start()
	local tickInterval = 1 / GameConfig.Combat.TickRate

	-- Any change to a base's board invalidates its cached aura totals.
	BaseService.onBoardChanged = function(state: BaseState)
		CombatService.markAurasDirty(state.Index)
	end

	RunService.Heartbeat:Connect(function(dt)
		-- Every frame: movement, spawning, and the auto-wave countdown. These are
		-- cheap and want the finest timestep available.
		for _, state in BaseService.all() do
			local run = runs[state.Index]
			if not run then
				continue
			end

			if state.Running then
				tickMovement(run, dt)
				tickSpawning(run, dt)
			elseif run.InterWaveTimer > 0 then
				run.InterWaveTimer -= dt
				if run.InterWaveTimer <= 0 then
					run.InterWaveTimer = 0
					if state.AutoWave and state.Owner then
						state.Integrity = state.MaxIntegrity
						beginWave(run, state.Wave + 1)
					end
				end
			end
		end

		-- Fixed step: targeting and damage, the expensive half.
		accumulator += dt
		if accumulator < tickInterval then
			return
		end
		accumulator = 0

		for _, state in BaseService.all() do
			local run = runs[state.Index]
			if run and state.Running then
				tickCombat(run)

				-- The wave ends when the queue is drained and nothing is alive.
				if #run.SpawnQueue == 0 and run.LiveCount == 0 then
					onWaveCleared(run)
				else
					BaseService.broadcast(state, run.RemainingThisWave, run.TotalThisWave)
				end
			end
		end
	end)
end

-- Drop a base's run entirely (used when a plot is released and reset).
function CombatService.clearBase(baseIndex: number)
	local run = runs[baseIndex]
	if run then
		clearRunEnemies(run)
		run.InterWaveTimer = 0
	end
end

return CombatService
