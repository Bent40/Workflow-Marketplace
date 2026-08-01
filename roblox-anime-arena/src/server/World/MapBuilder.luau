--!strict
--[[
	MapBuilder.luau

	Builds the arena at runtime: eight base plots arranged on a ring around a
	central hub, each with its own enemy track, core, spawn gate and placement
	area.

	Building the map in code rather than shipping it as a .rbxlx means the layout
	is reviewable in a diff and the base count is a single config change. Swap
	this module out for a hand-built map later; BaseService only depends on the
	`BasePlot` shape returned here.
]]

local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)

local MapBuilder = {}

export type BasePlot = {
	Index: number,
	Model: Model,
	Origin: CFrame,
	-- Ordered enemy path. Enemies walk Waypoints[1] -> Waypoints[#Waypoints].
	Waypoints: { Vector3 },
	TrackLength: number,
	Core: BasePart,
	SpawnGate: BasePart,
	Floor: BasePart,
	-- Axis-aligned bounds of the legal placement region, in world space.
	PlacementMin: Vector3,
	PlacementMax: Vector3,
	Nameplate: BillboardGui,
	NameLabel: TextLabel,
	WaveLabel: TextLabel,
	UnitFolder: Folder,
	EnemyFolder: Folder,
}

local PLOT_HEIGHT = 4
local TRACK_WIDTH = 14
local TRACK_Y = PLOT_HEIGHT / 2 + 0.1

--------------------------------------------------------------------------------
-- Part helpers
--------------------------------------------------------------------------------

local function makePart(props: { [string]: any }, parent: Instance): BasePart
	local part = Instance.new("Part")
	part.Anchored = true
	part.CanCollide = false
	part.CastShadow = false
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	part.Material = Enum.Material.SmoothPlastic
	for key, value in props do
		(part :: any)[key] = value
	end
	part.Parent = parent
	return part
end

--[[
	The enemy track: a three-lane serpentine that starts at the outer gate and
	ends at the core. Long enough that a mid-range unit placed centrally covers
	roughly a third of it, which is the ratio the placement economy is tuned to.
]]
local function buildWaypoints(origin: CFrame, size: Vector3): { Vector3 }
	local halfX = size.X / 2
	local halfZ = size.Z / 2
	local inset = 22

	-- Local-space points, later transformed by the plot's origin CFrame.
	local localPoints = {
		Vector3.new(0, TRACK_Y, -halfZ + 4), -- gate (outer edge)
		Vector3.new(0, TRACK_Y, -halfZ + inset),
		Vector3.new(halfX - inset, TRACK_Y, -halfZ + inset),
		Vector3.new(halfX - inset, TRACK_Y, -inset),
		Vector3.new(-halfX + inset, TRACK_Y, -inset),
		Vector3.new(-halfX + inset, TRACK_Y, inset),
		Vector3.new(halfX - inset, TRACK_Y, inset),
		Vector3.new(halfX - inset, TRACK_Y, halfZ - inset),
		Vector3.new(0, TRACK_Y, halfZ - inset),
		Vector3.new(0, TRACK_Y, halfZ - 26), -- core
	}

	local world: { Vector3 } = {}
	for _, point in localPoints do
		table.insert(world, origin:PointToWorldSpace(point))
	end
	return world
end

local function buildTrackVisual(waypoints: { Vector3 }, parent: Instance)
	for i = 1, #waypoints - 1 do
		local a = waypoints[i]
		local b = waypoints[i + 1]
		local delta = b - a
		local length = delta.Magnitude
		if length > 0.01 then
			makePart({
				Name = `TrackSegment{i}`,
				Size = Vector3.new(TRACK_WIDTH, 0.4, length + TRACK_WIDTH),
				CFrame = CFrame.lookAt(a + delta / 2, b) * CFrame.new(0, 0, 0),
				Color = Color3.fromRGB(58, 54, 78),
				Material = Enum.Material.Slate,
				Transparency = 0.15,
			}, parent)
		end
	end
end

--------------------------------------------------------------------------------
-- Plot construction
--------------------------------------------------------------------------------

local function buildPlot(index: number, origin: CFrame, parent: Instance): BasePlot
	local size = GameConfig.Bases.PlotSize
	local plotSize = Vector3.new(size.X, PLOT_HEIGHT, size.Z)

	local model = Instance.new("Model")
	model.Name = `Base{index}`
	model.Parent = parent

	local floor = makePart({
		Name = "Floor",
		Size = plotSize,
		CFrame = origin,
		Color = Color3.fromRGB(42, 44, 62),
		Material = Enum.Material.Concrete,
		CanCollide = true,
	}, model)
	model.PrimaryPart = floor

	-- A low rim so the plot reads as an arena rather than a slab.
	for _, offset in { Vector3.new(0, 0, -size.Z / 2), Vector3.new(0, 0, size.Z / 2) } do
		makePart({
			Name = "Rim",
			Size = Vector3.new(size.X, 5, 3),
			CFrame = origin * CFrame.new(offset + Vector3.new(0, 2.5, 0)),
			Color = Color3.fromRGB(70, 72, 100),
		}, model)
	end
	for _, offset in { Vector3.new(-size.X / 2, 0, 0), Vector3.new(size.X / 2, 0, 0) } do
		makePart({
			Name = "Rim",
			Size = Vector3.new(3, 5, size.Z),
			CFrame = origin * CFrame.new(offset + Vector3.new(0, 2.5, 0)),
			Color = Color3.fromRGB(70, 72, 100),
		}, model)
	end

	local waypoints = buildWaypoints(origin, size)
	buildTrackVisual(waypoints, model)

	local spawnGate = makePart({
		Name = "SpawnGate",
		Size = Vector3.new(TRACK_WIDTH + 6, 10, 3),
		CFrame = CFrame.new(waypoints[1]) * CFrame.new(0, 4, 0),
		Color = Color3.fromRGB(180, 60, 80),
		Material = Enum.Material.Neon,
		Transparency = 0.45,
	}, model)

	local core = makePart({
		Name = "Core",
		Size = Vector3.new(16, 16, 16),
		CFrame = CFrame.new(waypoints[#waypoints]) * CFrame.new(0, 8, 0),
		Color = Color3.fromRGB(96, 214, 255),
		Material = Enum.Material.Neon,
		Shape = Enum.PartType.Ball,
	}, model)

	-- Nameplate above the core: owner name and live wave, matching the reference's
	-- "<Player>'s Base / Wave: N" sign.
	local nameplate = Instance.new("BillboardGui")
	nameplate.Name = "Nameplate"
	nameplate.Size = UDim2.fromScale(20, 6)
	nameplate.StudsOffsetWorldSpace = Vector3.new(0, 16, 0)
	nameplate.AlwaysOnTop = false
	nameplate.MaxDistance = 600
	nameplate.Parent = core

	local nameLabel = Instance.new("TextLabel")
	nameLabel.Name = "Owner"
	nameLabel.Size = UDim2.fromScale(1, 0.58)
	nameLabel.BackgroundTransparency = 1
	nameLabel.Font = Enum.Font.GothamBold
	nameLabel.TextScaled = true
	nameLabel.TextColor3 = Color3.fromRGB(255, 255, 255)
	nameLabel.TextStrokeTransparency = 0.4
	nameLabel.Text = "Open Base"
	nameLabel.Parent = nameplate

	local waveLabel = Instance.new("TextLabel")
	waveLabel.Name = "Wave"
	waveLabel.Size = UDim2.fromScale(1, 0.42)
	waveLabel.Position = UDim2.fromScale(0, 0.58)
	waveLabel.BackgroundTransparency = 1
	waveLabel.Font = Enum.Font.GothamMedium
	waveLabel.TextScaled = true
	waveLabel.TextColor3 = Color3.fromRGB(190, 200, 220)
	waveLabel.TextStrokeTransparency = 0.6
	waveLabel.Text = "Waiting for a player"
	waveLabel.Parent = nameplate

	-- Spawn location so a claiming player lands on their own plot.
	local spawnLocation = Instance.new("SpawnLocation")
	spawnLocation.Name = "PlayerSpawn"
	spawnLocation.Size = Vector3.new(12, 1, 12)
	spawnLocation.CFrame = origin * CFrame.new(0, PLOT_HEIGHT / 2 + 0.5, size.Z / 2 - 8)
	spawnLocation.Anchored = true
	spawnLocation.CanCollide = true
	spawnLocation.Neutral = true
	spawnLocation.Enabled = false -- BaseService enables the owner's spawn only
	spawnLocation.Transparency = 0.6
	spawnLocation.Color = Color3.fromRGB(96, 214, 255)
	spawnLocation.Parent = model

	local unitFolder = Instance.new("Folder")
	unitFolder.Name = "Units"
	unitFolder.Parent = model

	local enemyFolder = Instance.new("Folder")
	enemyFolder.Name = "Enemies"
	enemyFolder.Parent = model

	local trackLength = 0
	for i = 1, #waypoints - 1 do
		trackLength += (waypoints[i + 1] - waypoints[i]).Magnitude
	end

	local halfExtent = Vector3.new(size.X / 2 - 6, 0, size.Z / 2 - 6)
	local center = origin.Position

	return {
		Index = index,
		Model = model,
		Origin = origin,
		Waypoints = waypoints,
		TrackLength = trackLength,
		Core = core,
		SpawnGate = spawnGate,
		Floor = floor,
		PlacementMin = Vector3.new(center.X - halfExtent.X, 0, center.Z - halfExtent.Z),
		PlacementMax = Vector3.new(center.X + halfExtent.X, 0, center.Z + halfExtent.Z),
		Nameplate = nameplate,
		NameLabel = nameLabel,
		WaveLabel = waveLabel,
		UnitFolder = unitFolder,
		EnemyFolder = enemyFolder,
	}
end

--------------------------------------------------------------------------------
-- Hub
--------------------------------------------------------------------------------

local function buildHub(parent: Instance)
	local hub = Instance.new("Model")
	hub.Name = "Hub"
	hub.Parent = parent

	makePart({
		Name = "HubFloor",
		Size = Vector3.new(220, 4, 220),
		CFrame = CFrame.new(0, 0, 0),
		Color = Color3.fromRGB(34, 36, 52),
		Material = Enum.Material.Marble,
		CanCollide = true,
	}, hub)

	-- Machine pedestals. These are interaction anchors the client attaches
	-- ProximityPrompts to; the machines themselves are UI, not world objects.
	local machines = {
		{ Name = "SummonAltar", Offset = Vector3.new(0, 0, -70), Color = Color3.fromRGB(120, 90, 220) },
		{ Name = "ShopStall", Offset = Vector3.new(-70, 0, 0), Color = Color3.fromRGB(90, 180, 140) },
		{ Name = "TraitMachine", Offset = Vector3.new(70, 0, 0), Color = Color3.fromRGB(220, 160, 70) },
		{ Name = "UpgradeTerminal", Offset = Vector3.new(0, 0, 70), Color = Color3.fromRGB(80, 150, 220) },
	}

	for _, machine in machines do
		local pedestal = makePart({
			Name = machine.Name,
			Size = Vector3.new(14, 12, 14),
			CFrame = CFrame.new(machine.Offset + Vector3.new(0, 8, 0)),
			Color = machine.Color,
			Material = Enum.Material.Neon,
			Transparency = 0.25,
			CanCollide = true,
		}, hub)

		local prompt = Instance.new("ProximityPrompt")
		prompt.Name = "Prompt"
		prompt.ActionText = "Open"
		prompt.ObjectText = machine.Name
		prompt.HoldDuration = 0
		prompt.MaxActivationDistance = 16
		prompt.RequiresLineOfSight = false
		prompt.Parent = pedestal
	end
end

--------------------------------------------------------------------------------
-- Entry point
--------------------------------------------------------------------------------

--[[
	Build the whole arena. Returns plots indexed 1..GameConfig.Bases.Count.
	Idempotent: an existing arena is destroyed and rebuilt.
]]
function MapBuilder.build(): { BasePlot }
	local existing = Workspace:FindFirstChild("Arena")
	if existing then
		existing:Destroy()
	end

	local arena = Instance.new("Folder")
	arena.Name = "Arena"
	arena.Parent = Workspace

	buildHub(arena)

	local plotsFolder = Instance.new("Folder")
	plotsFolder.Name = "Bases"
	plotsFolder.Parent = arena

	local count = GameConfig.Bases.Count
	local radius = GameConfig.Bases.RingRadius
	local plots: { BasePlot } = {}

	for i = 1, count do
		-- Evenly spaced on the ring, each plot facing the hub so every track runs
		-- outside-in toward the centre.
		local angle = (i - 1) / count * math.pi * 2
		local position = Vector3.new(math.cos(angle) * radius, 0, math.sin(angle) * radius)
		local origin = CFrame.lookAt(position, Vector3.new(0, position.Y, 0))
		plots[i] = buildPlot(i, origin, plotsFolder)
	end

	return plots
end

return MapBuilder
