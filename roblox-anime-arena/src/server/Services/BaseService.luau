--!strict
--[[
	BaseService.luau

	Owns the eight base plots: who holds which, unit placement on them, and the
	base integrity pool.

	Claiming
	--------
	A player claims the lowest free base index when their profile finishes
	loading. On leave the base enters a grace window (GameConfig.Bases.ReclaimGrace)
	during which only the original owner can reclaim it — that way a disconnect
	does not cost a wave-140 run to whoever joins next. After the window it is
	free for anyone.

	If all eight are held, the joining player becomes a spectator: they can still
	roll, shop and upgrade, and they are auto-assigned the moment a base frees up.
]]

local Players = game:GetService("Players")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)
local Net = require(Shared.Net)
local StatMath = require(Shared.Util.StatMath)
local Units = require(Shared.Config.Units)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local InventoryService = require(script.Parent.InventoryService)
local SyncService = require(script.Parent.SyncService)
local MapBuilder = require(script.Parent.Parent.World.MapBuilder)

type Profile = Types.Profile
type BasePlot = MapBuilder.BasePlot

export type PlacedUnitRecord = {
	Uid: string,
	UnitId: Units.UnitId,
	Position: Vector3,
	Model: Model,
	-- Combat bookkeeping, owned by CombatService.
	NextAttack: number,
}

export type BaseState = {
	Index: number,
	Plot: BasePlot,
	OwnerUserId: number?,
	Owner: Player?,
	-- Set when the owner leaves; the plot is reserved for them until this time.
	ReservedUntil: number,
	ReservedFor: number?,

	Wave: number,
	Running: boolean,
	AutoWave: boolean,
	Integrity: number,
	MaxIntegrity: number,

	Placed: { [string]: PlacedUnitRecord },
	PlacedCount: number,
}

local BaseService = {}

local plots: { BasePlot } = {}
local bases: { BaseState } = {}
local baseByPlayer: { [Player]: BaseState } = {}

--[[
	Set by CombatService at boot. Fired whenever the set of placed units changes,
	so the combat loop knows to recompute cached aura totals. A plain hook rather
	than a require, because CombatService already depends on BaseService and we
	are not introducing a cycle for one notification.
]]
BaseService.onBoardChanged = nil :: ((BaseState) -> ())?

local function notifyBoardChanged(state: BaseState)
	local hook = BaseService.onBoardChanged
	if hook then
		hook(state)
	end
end

--------------------------------------------------------------------------------
-- Integrity
--------------------------------------------------------------------------------

--[[
	Max integrity is the flat base value plus every placed unit's Health stat.
	This is what makes TANK units worth a slot: they do not soak hits themselves,
	they raise the pool the core draws from.
]]
local function recomputeIntegrity(state: BaseState)
	local profile = if state.Owner then DataService.get(state.Owner) else nil
	local total = GameConfig.Bases.BaseIntegrity

	if profile then
		for uid, record in state.Placed do
			local owned = profile.Inventory[uid]
			if owned then
				local stats = StatMath.compute(record.UnitId, owned.Level, owned.Trait, owned.Mutation, nil)
				total += stats.Health
			end
		end
	end

	local ratio = if state.MaxIntegrity > 0 then state.Integrity / state.MaxIntegrity else 1
	state.MaxIntegrity = math.floor(total)
	-- Preserve the damage already taken as a proportion, so placing a tank
	-- mid-wave heals proportionally rather than fully.
	state.Integrity = math.clamp(math.floor(state.MaxIntegrity * ratio), 0, state.MaxIntegrity)

	notifyBoardChanged(state)
end

BaseService.recomputeIntegrity = recomputeIntegrity

--------------------------------------------------------------------------------
-- Replication
--------------------------------------------------------------------------------

local function toInfo(state: BaseState, enemiesLeft: number?, enemiesTotal: number?): Types.BaseInfo
	return {
		Index = state.Index,
		OwnerUserId = state.OwnerUserId,
		OwnerName = if state.Owner then state.Owner.DisplayName else nil,
		Wave = state.Wave,
		Running = state.Running,
		Integrity = state.Integrity,
		MaxIntegrity = state.MaxIntegrity,
		EnemiesLeft = enemiesLeft or 0,
		EnemiesTotal = enemiesTotal or 0,
	}
end

BaseService.toInfo = toInfo

local function updateNameplate(state: BaseState)
	local plot = state.Plot
	if state.Owner then
		plot.NameLabel.Text = `{state.Owner.DisplayName}'s Base`
		if state.Running then
			plot.WaveLabel.Text = `Wave: {state.Wave}`
		else
			plot.WaveLabel.Text = if state.Wave > 0 then `Wave: {state.Wave} — stopped` else "Ready"
		end
	else
		plot.NameLabel.Text = "Open Base"
		plot.WaveLabel.Text = "Waiting for a player"
	end
end

BaseService.updateNameplate = updateNameplate

function BaseService.broadcast(state: BaseState, enemiesLeft: number?, enemiesTotal: number?)
	updateNameplate(state)
	Net.event("BaseUpdated"):FireAllClients(toInfo(state, enemiesLeft, enemiesTotal))
end

function BaseService.broadcastAll()
	local infos: { Types.BaseInfo } = {}
	for _, state in bases do
		table.insert(infos, toInfo(state))
	end
	Net.event("BasesUpdated"):FireAllClients(infos)
end

--------------------------------------------------------------------------------
-- Claim / release
--------------------------------------------------------------------------------

local function clearPlacements(state: BaseState)
	for _, record in state.Placed do
		if record.Model.Parent then
			record.Model:Destroy()
		end
	end
	state.Placed = {}
	state.PlacedCount = 0
end

local function resetBase(state: BaseState)
	clearPlacements(state)
	state.Wave = 0
	state.Running = false
	state.AutoWave = false
	state.MaxIntegrity = GameConfig.Bases.BaseIntegrity
	state.Integrity = state.MaxIntegrity
	state.Plot.EnemyFolder:ClearAllChildren()
end

BaseService.resetBase = resetBase

local function findBaseFor(player: Player): BaseState?
	local now = os.time()

	-- A returning owner gets their reserved plot back first.
	for _, state in bases do
		if not state.Owner and state.ReservedFor == player.UserId and now < state.ReservedUntil then
			return state
		end
	end

	-- Otherwise the lowest plot that is neither owned nor under someone else's
	-- reservation.
	for _, state in bases do
		if not state.Owner and (state.ReservedFor == nil or now >= state.ReservedUntil) then
			return state
		end
	end

	return nil
end

function BaseService.claim(player: Player): BaseState?
	if baseByPlayer[player] then
		return baseByPlayer[player]
	end

	local state = findBaseFor(player)
	if not state then
		SyncService.toast(player, "info", "All 8 bases are taken — you'll be assigned one as soon as a base frees up.")
		return nil
	end

	local reclaiming = state.ReservedFor == player.UserId and os.time() < state.ReservedUntil

	state.Owner = player
	state.OwnerUserId = player.UserId
	state.ReservedFor = nil
	state.ReservedUntil = 0
	baseByPlayer[player] = state

	if not reclaiming then
		resetBase(state)
	end

	-- Only the owner's spawn point is live, so respawns land on the right plot.
	local spawnLocation = state.Plot.Model:FindFirstChild("PlayerSpawn")
	if spawnLocation and spawnLocation:IsA("SpawnLocation") then
		spawnLocation.Enabled = true
		player.RespawnLocation = spawnLocation
	end

	recomputeIntegrity(state)
	BaseService.broadcast(state)
	BaseService.broadcastAll()

	if reclaiming then
		SyncService.toast(player, "success", `Welcome back — base {state.Index} restored at wave {state.Wave}.`)
	end

	return state
end

function BaseService.release(player: Player)
	local state = baseByPlayer[player]
	if not state then
		return
	end

	baseByPlayer[player] = nil
	state.Owner = nil
	state.OwnerUserId = nil
	state.Running = false
	state.ReservedFor = player.UserId
	state.ReservedUntil = os.time() + GameConfig.Bases.ReclaimGrace

	local spawnLocation = state.Plot.Model:FindFirstChild("PlayerSpawn")
	if spawnLocation and spawnLocation:IsA("SpawnLocation") then
		spawnLocation.Enabled = false
	end

	BaseService.broadcast(state)
	BaseService.broadcastAll()

	-- After the grace window, wipe the run so the next player starts clean.
	task.delay(GameConfig.Bases.ReclaimGrace + 1, function()
		if not state.Owner and state.ReservedFor == player.UserId then
			state.ReservedFor = nil
			state.ReservedUntil = 0
			resetBase(state)
			BaseService.broadcast(state)
			BaseService.broadcastAll()
			BaseService.assignWaiting()
		end
	end)
end

-- Give a free base to anyone who joined while all eight were held.
function BaseService.assignWaiting()
	for _, player in Players:GetPlayers() do
		if not baseByPlayer[player] and DataService.get(player) then
			local claimed = BaseService.claim(player)
			if claimed then
				SyncService.toast(player, "success", `Base {claimed.Index} is yours — go defend it!`)
			end
		end
	end
end

--------------------------------------------------------------------------------
-- Lookups
--------------------------------------------------------------------------------

function BaseService.forPlayer(player: Player): BaseState?
	return baseByPlayer[player]
end

function BaseService.byIndex(index: number): BaseState?
	return bases[index]
end

function BaseService.all(): { BaseState }
	return bases
end

--------------------------------------------------------------------------------
-- Unit placement
--------------------------------------------------------------------------------

--[[
	A position is legal when it is inside the plot's placement box and far enough
	from the enemy track that units are not standing in the lane.
]]
local MIN_TRACK_CLEARANCE = 9

local function isOnTrack(plot: BasePlot, position: Vector3): boolean
	local flat = Vector3.new(position.X, 0, position.Z)
	for i = 1, #plot.Waypoints - 1 do
		local a = plot.Waypoints[i]
		local b = plot.Waypoints[i + 1]
		local segA = Vector3.new(a.X, 0, a.Z)
		local segB = Vector3.new(b.X, 0, b.Z)
		local segment = segB - segA
		local lengthSq = segment:Dot(segment)
		if lengthSq > 0.001 then
			local t = math.clamp((flat - segA):Dot(segment) / lengthSq, 0, 1)
			local closest = segA + segment * t
			if (flat - closest).Magnitude < MIN_TRACK_CLEARANCE then
				return true
			end
		end
	end
	return false
end

local MIN_UNIT_SPACING = 7

local function buildUnitModel(unitId: Units.UnitId, position: Vector3, parent: Instance, owned: Types.OwnedUnit): Model
	local Mutations = require(Shared.Config.Mutations)
	local unit = Units.expect(unitId)
	local mutation = Mutations.get(owned.Mutation)

	local model = Instance.new("Model")
	model.Name = unitId

	-- A placeholder body. Swap this for a rigged R15 character or an imported
	-- mesh per unit later; nothing else in the codebase depends on the shape.
	local body = Instance.new("Part")
	body.Name = "Body"
	body.Size = Vector3.new(4, 8, 4)
	body.CFrame = CFrame.new(position + Vector3.new(0, 4, 0))
	body.Anchored = true
	body.CanCollide = false
	body.Material = mutation.Material
	body.Color = if mutation.Id == "None" then unit.Color else mutation.Color
	body.TopSurface = Enum.SurfaceType.Smooth
	body.BottomSurface = Enum.SurfaceType.Smooth
	body.Parent = model
	model.PrimaryPart = body

	local head = Instance.new("Part")
	head.Name = "Head"
	head.Shape = Enum.PartType.Ball
	head.Size = Vector3.new(3.4, 3.4, 3.4)
	head.CFrame = CFrame.new(position + Vector3.new(0, 9.4, 0))
	head.Anchored = true
	head.CanCollide = false
	head.Material = mutation.Material
	head.Color = if mutation.Id == "None" then unit.Color else mutation.Color
	head.Parent = model

	if mutation.Glow > 0 then
		local light = Instance.new("PointLight")
		light.Brightness = mutation.Glow * 4
		light.Range = 14
		light.Color = mutation.Color
		light.Parent = body
	end

	-- Range indicator, hidden by default; the client toggles it on selection.
	local ring = Instance.new("Part")
	ring.Name = "RangeRing"
	ring.Shape = Enum.PartType.Cylinder
	ring.Size = Vector3.new(0.2, unit.Range * 2, unit.Range * 2)
	ring.CFrame = CFrame.new(position + Vector3.new(0, 0.3, 0)) * CFrame.Angles(0, 0, math.pi / 2)
	ring.Anchored = true
	ring.CanCollide = false
	ring.Material = Enum.Material.Neon
	ring.Color = unit.Color
	ring.Transparency = 1
	ring.Parent = model

	local label = Instance.new("BillboardGui")
	label.Size = UDim2.fromScale(10, 2.2)
	label.StudsOffsetWorldSpace = Vector3.new(0, 7, 0)
	label.MaxDistance = 220
	label.Parent = head

	local text = Instance.new("TextLabel")
	text.Size = UDim2.fromScale(1, 1)
	text.BackgroundTransparency = 1
	text.Font = Enum.Font.GothamBold
	text.TextScaled = true
	text.TextColor3 = Color3.fromRGB(255, 255, 255)
	text.TextStrokeTransparency = 0.4
	text.Text = if owned.Level > 1 then `{unit.Display} Lv.{owned.Level}` else unit.Display
	text.Parent = label

	model.Parent = parent
	return model
end

function BaseService.placeUnit(
	player: Player,
	profile: Profile,
	uid: string,
	position: Vector3
): Types.Result<{ position: Vector3 }>
	local state = baseByPlayer[player]
	if not state then
		return { ok = false, err = "You don't have a base yet." }
	end

	local owned = profile.Inventory[uid]
	if not owned then
		return { ok = false, err = "You do not own that unit." }
	end
	if state.Placed[uid] then
		return { ok = false, err = "That unit is already placed." }
	end
	if typeof(position) ~= "Vector3" then
		return { ok = false, err = "Invalid position." }
	end

	local slots = CurrencyService.getSlots(profile)
	if state.PlacedCount >= slots then
		return { ok = false, err = `All {slots} slots are full. Buy a Slot Upgrade for more.` }
	end

	local unit = Units.expect(owned.Id)

	-- MaxCopies is per board, not per inventory.
	local sameId = 0
	for _, record in state.Placed do
		if record.UnitId == owned.Id then
			sameId += 1
		end
	end
	if sameId >= unit.MaxCopies then
		return { ok = false, err = `You can only place {unit.MaxCopies}x {unit.Display}.` }
	end

	local plot = state.Plot
	-- Snap to the plot surface; never trust a client-supplied Y.
	local grounded = Vector3.new(position.X, plot.Floor.Position.Y + plot.Floor.Size.Y / 2, position.Z)

	if
		grounded.X < plot.PlacementMin.X
		or grounded.X > plot.PlacementMax.X
		or grounded.Z < plot.PlacementMin.Z
		or grounded.Z > plot.PlacementMax.Z
	then
		return { ok = false, err = "Place that inside your own base." }
	end
	if isOnTrack(plot, grounded) then
		return { ok = false, err = "You can't build on the enemy path." }
	end
	for _, record in state.Placed do
		if (Vector3.new(record.Position.X, 0, record.Position.Z) - Vector3.new(grounded.X, 0, grounded.Z)).Magnitude
			< MIN_UNIT_SPACING
		then
			return { ok = false, err = "Too close to another unit." }
		end
	end

	-- Deploying costs gold, which is the in-run resource sink.
	if not CurrencyService.spendGold(player, profile, unit.PlaceCost) then
		return { ok = false, err = `Need {unit.PlaceCost} Gold to deploy {unit.Display}.` }
	end

	local model = buildUnitModel(owned.Id, grounded, plot.UnitFolder, owned)

	state.Placed[uid] = {
		Uid = uid,
		UnitId = owned.Id,
		Position = grounded,
		Model = model,
		NextAttack = 0,
	}
	state.PlacedCount += 1

	if not InventoryService.isInLoadout(profile, uid) then
		table.insert(profile.Loadout, uid)
		DataService.markDirty(player)
	end

	recomputeIntegrity(state)
	SyncService.push(player)
	BaseService.broadcast(state)

	return { ok = true, data = { position = grounded } }
end

function BaseService.removeUnit(player: Player, profile: Profile, uid: string): Types.Result<{ refund: number }>
	local state = baseByPlayer[player]
	if not state then
		return { ok = false, err = "You don't have a base yet." }
	end

	local record = state.Placed[uid]
	if not record then
		return { ok = false, err = "That unit isn't placed." }
	end

	if record.Model.Parent then
		record.Model:Destroy()
	end
	state.Placed[uid] = nil
	state.PlacedCount = math.max(0, state.PlacedCount - 1)

	InventoryService.removeFromLoadout(profile, uid)

	-- Half the deploy cost back, so repositioning is cheap but not free.
	local refund = math.floor(Units.expect(record.UnitId).PlaceCost * 0.5)
	CurrencyService.addGold(player, profile, refund)

	recomputeIntegrity(state)
	DataService.markDirty(player)
	SyncService.push(player)
	BaseService.broadcast(state)

	return { ok = true, data = { refund = refund } }
end

-- Called when a unit leaves the inventory (sold or merged) while placed.
function BaseService.onUnitRemovedFromInventory(player: Player, uid: string)
	local state = baseByPlayer[player]
	if not state then
		return
	end
	local record = state.Placed[uid]
	if not record then
		return
	end
	if record.Model.Parent then
		record.Model:Destroy()
	end
	state.Placed[uid] = nil
	state.PlacedCount = math.max(0, state.PlacedCount - 1)
	recomputeIntegrity(state)
	BaseService.broadcast(state)
end

--------------------------------------------------------------------------------
-- Lifecycle
--------------------------------------------------------------------------------

function BaseService.start()
	plots = MapBuilder.build()

	for index, plot in plots do
		bases[index] = {
			Index = index,
			Plot = plot,
			OwnerUserId = nil,
			Owner = nil,
			ReservedUntil = 0,
			ReservedFor = nil,
			Wave = 0,
			Running = false,
			AutoWave = false,
			Integrity = GameConfig.Bases.BaseIntegrity,
			MaxIntegrity = GameConfig.Bases.BaseIntegrity,
			Placed = {},
			PlacedCount = 0,
		}
		updateNameplate(bases[index])
	end

	DataService.onLoaded(function(player)
		BaseService.claim(player)
	end)

	Players.PlayerRemoving:Connect(function(player)
		BaseService.release(player)
	end)
end

return BaseService
