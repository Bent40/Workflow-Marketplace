--!strict
--[[
	PlacementController.luau

	Deploy flow. Picking DEPLOY on a unit puts the client into placement mode: a
	translucent ghost follows the cursor across the player's own plot, tinted by
	whether the spot is legal, and a click sends the position to the server.

	The legality preview here is a courtesy, not a gate. BaseService re-checks
	bounds, track clearance, spacing, slots and cost, and the ghost turning green
	means nothing to the server.
]]

local ContextActionService = game:GetService("ContextActionService")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local State = require(script.Parent.State)

local PlacementController = {}

local camera = Workspace.CurrentCamera

local ghost: Model? = nil
local ghostBody: BasePart? = nil
local ghostRing: BasePart? = nil
local activeUid: string? = nil
local renderConnection: RBXScriptConnection? = nil
local hintGui: Frame? = nil
local lastValid = false
local lastPosition: Vector3? = nil

local ACTION_PLACE = "AnimeArena_Place"
local ACTION_CANCEL = "AnimeArena_CancelPlace"

local function hud()
	return require(script.Parent.HudController)
end

--------------------------------------------------------------------------------
-- Plot lookup
--------------------------------------------------------------------------------

local function myPlotModel(): Model?
	local index = State.myBaseIndex
	if not index then
		return nil
	end
	local arena = Workspace:FindFirstChild("Arena")
	local basesFolder = arena and arena:FindFirstChild("Bases")
	local model = basesFolder and basesFolder:FindFirstChild(`Base{index}`)
	return if model and model:IsA("Model") then model else nil
end

--------------------------------------------------------------------------------
-- Ghost
--------------------------------------------------------------------------------

local function destroyGhost()
	if ghost then
		ghost:Destroy()
	end
	ghost = nil
	ghostBody = nil
	ghostRing = nil
end

local function buildGhost(unitId: string)
	destroyGhost()

	local unit = Units.expect(unitId)

	local model = Instance.new("Model")
	model.Name = "PlacementGhost"

	local body = Instance.new("Part")
	body.Size = Vector3.new(4, 8, 4)
	body.Anchored = true
	body.CanCollide = false
	body.CanQuery = false
	body.Material = Enum.Material.Neon
	body.Color = unit.Color
	body.Transparency = 0.45
	body.Parent = model

	local ring = Instance.new("Part")
	ring.Shape = Enum.PartType.Cylinder
	ring.Size = Vector3.new(0.3, unit.Range * 2, unit.Range * 2)
	ring.Anchored = true
	ring.CanCollide = false
	ring.CanQuery = false
	ring.Material = Enum.Material.Neon
	ring.Color = unit.Color
	ring.Transparency = 0.82
	ring.Parent = model

	model.Parent = Workspace
	ghost = model
	ghostBody = body
	ghostRing = ring
end

--------------------------------------------------------------------------------
-- Hint bar
--------------------------------------------------------------------------------

local function showHint(screen: ScreenGui, unitId: string)
	if hintGui then
		hintGui:Destroy()
	end

	local unit = Units.expect(unitId)

	local bar = Widgets.frame({
		Name = "PlacementHint",
		Size = UDim2.fromOffset(420, 54),
		Position = UDim2.new(0.5, 0, 1, -100),
		AnchorPoint = Vector2.new(0.5, 1),
		BackgroundColor3 = Theme.Color.Panel,
		ZIndex = Theme.Layer.Overlay,
	}, screen)
	Widgets.corner(Theme.Radius.Medium, bar)
	Widgets.stroke(Theme.Color.Accent, 1.5, bar)

	Widgets.label({
		Text = `Placing <b>{unit.Display}</b> — {Format.abbreviate(unit.PlaceCost)} gold`,
		Size = UDim2.new(1, -20, 0, 24),
		Position = UDim2.fromOffset(10, 4),
		TextSize = 15,
		TextXAlignment = Enum.TextXAlignment.Center,
		ZIndex = Theme.Layer.Overlay + 1,
	}, bar)

	Widgets.label({
		Name = "Status",
		Text = "Click to place · Right-click or Esc to cancel",
		Size = UDim2.new(1, -20, 0, 20),
		Position = UDim2.fromOffset(10, 28),
		TextSize = 12,
		TextColor3 = Theme.Color.TextMuted,
		TextXAlignment = Enum.TextXAlignment.Center,
		ZIndex = Theme.Layer.Overlay + 1,
	}, bar)

	hintGui = bar
end

local function setHintStatus(text: string, color: Color3)
	if not hintGui then
		return
	end
	local status = hintGui:FindFirstChild("Status")
	if status and status:IsA("TextLabel") then
		status.Text = text
		status.TextColor3 = color
	end
end

--------------------------------------------------------------------------------
-- Targeting
--------------------------------------------------------------------------------

--[[
	Raycast the cursor onto the player's own plot floor.

	The filter is an allowlist of exactly one part so a unit model, an enemy, or
	another player's plot can never be mistaken for ground.
]]
local function cursorGroundPoint(): Vector3?
	local plot = myPlotModel()
	if not plot then
		return nil
	end
	local floor = plot:FindFirstChild("Floor")
	if not floor or not floor:IsA("BasePart") then
		return nil
	end

	local mouseLocation = UserInputService:GetMouseLocation()
	local unitRay = camera:ViewportPointToRay(mouseLocation.X, mouseLocation.Y)

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Include
	params.FilterDescendantsInstances = { floor }

	local hit = Workspace:Raycast(unitRay.Origin, unitRay.Direction * 2000, params)
	return if hit then hit.Position else nil
end

--[[
	Client-side legality preview. Mirrors BaseService's rules closely enough to be
	useful, and is allowed to be wrong — the server decides.
]]
local TRACK_CLEARANCE = 9
local UNIT_SPACING = 7

local function previewValid(position: Vector3): (boolean, string)
	local plot = myPlotModel()
	if not plot then
		return false, "No base"
	end

	-- Track clearance, measured against the visible track segments.
	for _, child in plot:GetChildren() do
		if child:IsA("BasePart") and string.sub(child.Name, 1, 12) == "TrackSegment" then
			local localPoint = child.CFrame:PointToObjectSpace(position)
			local half = child.Size / 2
			local dx = math.max(math.abs(localPoint.X) - half.X, 0)
			local dz = math.max(math.abs(localPoint.Z) - half.Z, 0)
			if math.sqrt(dx * dx + dz * dz) < TRACK_CLEARANCE - 7 then
				return false, "Can't build on the enemy path"
			end
		end
	end

	local unitFolder = plot:FindFirstChild("Units")
	if unitFolder then
		for _, model in unitFolder:GetChildren() do
			if model:IsA("Model") and model.PrimaryPart then
				local other = model.PrimaryPart.Position
				local flat = Vector3.new(other.X - position.X, 0, other.Z - position.Z)
				if flat.Magnitude < UNIT_SPACING then
					return false, "Too close to another unit"
				end
			end
		end
	end

	return true, "Click to place"
end

--------------------------------------------------------------------------------
-- Mode control
--------------------------------------------------------------------------------

local function stopPlacement()
	if renderConnection then
		renderConnection:Disconnect()
		renderConnection = nil
	end
	ContextActionService:UnbindAction(ACTION_PLACE)
	ContextActionService:UnbindAction(ACTION_CANCEL)

	destroyGhost()
	if hintGui then
		hintGui:Destroy()
		hintGui = nil
	end

	activeUid = nil
	lastPosition = nil
	lastValid = false
end

PlacementController.cancel = stopPlacement

local function commitPlacement()
	local uid = activeUid
	local position = lastPosition
	if not uid or not position or not lastValid then
		hud().toast("error", "Pick a clear spot on your base.")
		return
	end

	local result = State.request("PlaceUnit", uid, position)
	if result.ok then
		hud().toast("success", "Deployed!")
		stopPlacement()
	else
		hud().toast("error", result.err or "Could not place there.")
	end
end

function PlacementController.begin(screen: ScreenGui, uid: string)
	local owned = State.ownedUnit(uid)
	if not owned then
		hud().toast("error", "You no longer own that unit.")
		return
	end
	if not State.myBaseIndex then
		hud().toast("error", "You don't have a base yet.")
		return
	end

	stopPlacement()
	activeUid = uid

	buildGhost(owned.Id)
	showHint(screen, owned.Id)

	renderConnection = RunService.RenderStepped:Connect(function()
		local body = ghostBody
		local ring = ghostRing
		if not body or not ring then
			return
		end

		local point = cursorGroundPoint()
		if not point then
			lastValid = false
			lastPosition = nil
			setHintStatus("Aim at your own base", Theme.Color.Warning)
			return
		end

		local valid, reason = previewValid(point)
		lastValid = valid
		lastPosition = point

		body.Position = point + Vector3.new(0, 4, 0)
		ring.CFrame = CFrame.new(point + Vector3.new(0, 0.4, 0)) * CFrame.Angles(0, 0, math.pi / 2)

		local tint = if valid then Theme.Color.Success else Theme.Color.Danger
		body.Color = tint
		ring.Color = tint
		setHintStatus(reason, if valid then Theme.Color.Success else Theme.Color.Danger)
	end)

	ContextActionService:BindAction(ACTION_PLACE, function(_, inputState)
		if inputState == Enum.UserInputState.Begin then
			commitPlacement()
		end
		return Enum.ContextActionResult.Sink
	end, false, Enum.UserInputType.MouseButton1, Enum.UserInputType.Touch)

	ContextActionService:BindAction(ACTION_CANCEL, function(_, inputState)
		if inputState == Enum.UserInputState.Begin then
			stopPlacement()
		end
		return Enum.ContextActionResult.Sink
	end, false, Enum.UserInputType.MouseButton2, Enum.KeyCode.Escape)
end

--------------------------------------------------------------------------------
-- Removing a placed unit
--------------------------------------------------------------------------------

--[[
	Clicking a placed unit while not in placement mode picks it back up. Bound
	from init so the whole world-interaction surface lives in one controller.
]]
function PlacementController.tryPickup()
	if activeUid then
		return
	end

	local plot = myPlotModel()
	if not plot then
		return
	end
	local unitFolder = plot:FindFirstChild("Units")
	if not unitFolder then
		return
	end

	local mouseLocation = UserInputService:GetMouseLocation()
	local unitRay = camera:ViewportPointToRay(mouseLocation.X, mouseLocation.Y)

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Include
	params.FilterDescendantsInstances = { unitFolder }

	local hit = Workspace:Raycast(unitRay.Origin, unitRay.Direction * 2000, params)
	if not hit then
		return
	end

	local model = hit.Instance:FindFirstAncestorOfClass("Model")
	if not model or model.Parent ~= unitFolder then
		return
	end

	-- The model name is the unit id; find which owned uid is standing there.
	local profile = State.profile
	if not profile then
		return
	end

	for _, uid in profile.Loadout do
		local owned = State.ownedUnit(uid)
		if owned and owned.Id == model.Name then
			local result = State.request("RemoveUnit", uid)
			if result.ok then
				hud().toast("info", `Picked up — refunded {Format.abbreviate((result.data :: any).refund)} gold.`)
			end
			return
		end
	end
end

function PlacementController.isActive(): boolean
	return activeUid ~= nil
end

return PlacementController
