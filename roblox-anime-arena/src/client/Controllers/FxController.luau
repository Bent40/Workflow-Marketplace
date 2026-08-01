--!strict
--[[
	FxController.luau

	Combat feedback: attack tracers, gold pop-ups on kills and a screen flash when
	the base takes a hit.

	All of it is local and disposable. FX only render for the local player's own
	base — drawing tracers for all eight bases at once is a frame-rate problem
	with no gameplay value, since you cannot see another plot's units clearly from
	your own anyway.
]]

local Debris = game:GetService("Debris")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local State = require(script.Parent.State)

local FxController = {}

-- Cap concurrent tracers so a Full-board attack cannot spawn 120 parts at once.
local MAX_TRACERS = 40
local liveTracers = 0

local function plotFor(baseIndex: number): Model?
	local arena = Workspace:FindFirstChild("Arena")
	local basesFolder = arena and arena:FindFirstChild("Bases")
	local model = basesFolder and basesFolder:FindFirstChild(`Base{baseIndex}`)
	return if model and model:IsA("Model") then model else nil
end

local function findEnemyPart(baseIndex: number, enemyKey: number): BasePart?
	-- Enemy parts are not keyed by name on the client, so FX resolve position by
	-- proximity in the enemy folder instead. Good enough for a tracer; nothing
	-- gameplay-relevant depends on picking the exact instance.
	local plot = plotFor(baseIndex)
	local enemies = plot and plot:FindFirstChild("Enemies")
	if not enemies then
		return nil
	end
	local children = enemies:GetChildren()
	if #children == 0 then
		return nil
	end
	local pick = children[(enemyKey - 1) % #children + 1]
	return if pick and pick:IsA("BasePart") then pick else nil
end

--------------------------------------------------------------------------------
-- Tracers
--------------------------------------------------------------------------------

function FxController.onUnitFired(baseIndex: number, uid: string, targetKeys: { number }, isCrit: boolean)
	if baseIndex ~= State.myBaseIndex then
		return
	end
	if liveTracers >= MAX_TRACERS then
		return
	end

	local owned = State.ownedUnit(uid)
	if not owned then
		return
	end

	local plot = plotFor(baseIndex)
	local unitFolder = plot and plot:FindFirstChild("Units")
	if not unitFolder then
		return
	end

	local source: BasePart? = nil
	for _, model in unitFolder:GetChildren() do
		if model:IsA("Model") and model.Name == owned.Id and model.PrimaryPart then
			source = model.PrimaryPart
			break
		end
	end
	if not source then
		return
	end

	local unit = Units.expect(owned.Id)
	local color = if isCrit then Theme.Color.Warning else unit.Color

	-- One tracer to the first target keeps the read clear even for area attacks.
	local target = findEnemyPart(baseIndex, targetKeys[1] or 1)
	if not target then
		return
	end

	local origin = source.Position + Vector3.new(0, 3, 0)
	local delta = target.Position - origin
	local distance = delta.Magnitude
	if distance < 0.5 then
		return
	end

	local beam = Instance.new("Part")
	beam.Anchored = true
	beam.CanCollide = false
	beam.CanQuery = false
	beam.CanTouch = false
	beam.Material = Enum.Material.Neon
	beam.Color = color
	beam.Size = Vector3.new(if isCrit then 0.5 else 0.25, if isCrit then 0.5 else 0.25, distance)
	beam.CFrame = CFrame.lookAt(origin + delta / 2, target.Position)
	beam.Transparency = 0.15
	beam.Parent = Workspace

	liveTracers += 1
	TweenService:Create(beam, TweenInfo.new(0.16), { Transparency = 1 }):Play()
	task.delay(0.2, function()
		liveTracers -= 1
		beam:Destroy()
	end)
end

--------------------------------------------------------------------------------
-- Kill reward pop-up
--------------------------------------------------------------------------------

function FxController.onEnemyDied(baseIndex: number, enemyKey: number, bounty: number)
	if baseIndex ~= State.myBaseIndex or bounty <= 0 then
		return
	end

	local part = findEnemyPart(baseIndex, enemyKey)
	if not part then
		return
	end

	local anchor = Instance.new("Part")
	anchor.Anchored = true
	anchor.CanCollide = false
	anchor.CanQuery = false
	anchor.Transparency = 1
	anchor.Size = Vector3.one
	anchor.Position = part.Position + Vector3.new(0, 3, 0)
	anchor.Parent = Workspace

	local billboard = Instance.new("BillboardGui")
	billboard.Size = UDim2.fromScale(6, 1.6)
	billboard.AlwaysOnTop = true
	billboard.MaxDistance = 220
	billboard.Parent = anchor

	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.FontFace = Theme.Font.Numeric
	label.TextScaled = true
	label.TextColor3 = Theme.Color.Gold
	label.TextStrokeTransparency = 0.4
	label.Text = `+{Format.abbreviate(bounty)}`
	label.Parent = billboard

	TweenService:Create(anchor, TweenInfo.new(0.7, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
		Position = anchor.Position + Vector3.new(0, 7, 0),
	}):Play()
	TweenService:Create(label, TweenInfo.new(0.7), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()

	Debris:AddItem(anchor, 0.8)
end

--------------------------------------------------------------------------------
-- Wave banners
--------------------------------------------------------------------------------

local banner: TextLabel? = nil

function FxController.init(screen: ScreenGui)
	local label = Instance.new("TextLabel")
	label.Name = "WaveBanner"
	label.Size = UDim2.new(1, 0, 0, 60)
	label.Position = UDim2.fromScale(0, 0.28)
	label.BackgroundTransparency = 1
	label.FontFace = Theme.Font.Heading
	label.TextSize = 44
	label.TextColor3 = Theme.Color.Text
	label.TextStrokeTransparency = 0.5
	label.TextTransparency = 1
	label.Text = ""
	label.ZIndex = Theme.Layer.Overlay
	label.Parent = screen

	banner = label
end

local function flashBanner(text: string, color: Color3)
	local label = banner
	if not label then
		return
	end

	label.Text = text
	label.TextColor3 = color
	label.TextTransparency = 0
	label.Position = UDim2.fromScale(0, 0.30)

	TweenService:Create(label, TweenInfo.new(1.1, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
		TextTransparency = 1,
		Position = UDim2.fromScale(0, 0.24),
	}):Play()
end

function FxController.onWaveStarted(baseIndex: number, wave: number)
	if baseIndex ~= State.myBaseIndex then
		return
	end
	flashBanner(`WAVE {wave}`, Theme.Color.Text)
end

function FxController.onWaveCleared(baseIndex: number, wave: number, bonus: number)
	if baseIndex ~= State.myBaseIndex then
		return
	end
	flashBanner(`WAVE {wave} CLEARED  +{Format.abbreviate(bonus)}`, Theme.Color.Success)
end

function FxController.onBaseFell(baseIndex: number, wave: number)
	if baseIndex ~= State.myBaseIndex then
		return
	end
	flashBanner(`BASE FELL — WAVE {wave}`, Theme.Color.Danger)
end

return FxController
