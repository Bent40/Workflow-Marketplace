--!strict
--[[
	HudController.luau

	The always-on layer: currency pills, the wave panel, the side menu buttons,
	the rare-roll feed and toasts.

	Layout follows the reference's screen grammar — currencies top-left, wave
	state top-centre, navigation down the right edge, roll action bottom-centre —
	because that is what players of this genre already have muscle memory for.
]]

local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Rarities = require(Shared.Config.Rarities)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local HudController = {}

local player = Players.LocalPlayer

local goldLabel: TextLabel
local gemLabel: TextLabel
local boostLabel: TextLabel
local waveLabel: TextLabel
local enemyLabel: TextLabel
local integrityFill: Frame
local startButton: TextButton
local autoButton: TextButton
local feedFrame: Frame
local toastHolder: Frame

local autoWaveOn = false

--------------------------------------------------------------------------------
-- Top bar
--------------------------------------------------------------------------------

local function buildTopBar(parent: Instance)
	local bar = Widgets.frame({
		Name = "TopBar",
		Size = UDim2.new(0, 360, 0, 96),
		Position = UDim2.fromOffset(16, 16),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Hud,
	}, parent)

	local _, gold = Widgets.currencyPill("🪙", Theme.Color.Gold, bar)
	goldLabel = gold

	local gemPill, gems = Widgets.currencyPill("💎", Theme.Color.Gem, bar)
	gemPill.Position = UDim2.fromOffset(0, 44)
	gemLabel = gems

	boostLabel = Widgets.label({
		Text = "",
		Size = UDim2.new(0, 180, 0, 20),
		Position = UDim2.fromOffset(176, 12),
		TextSize = 13,
		TextColor3 = Theme.Color.Success,
	}, bar)

	for _, descendant in bar:GetDescendants() do
		if descendant:IsA("GuiObject") then
			descendant.ZIndex = Theme.Layer.Hud + 1
		end
	end
end

--------------------------------------------------------------------------------
-- Wave panel
--------------------------------------------------------------------------------

local function buildWavePanel(parent: Instance)
	local panel = Widgets.frame({
		Name = "WavePanel",
		Size = UDim2.fromOffset(260, 112),
		Position = UDim2.new(0.5, 0, 0, 16),
		AnchorPoint = Vector2.new(0.5, 0),
		BackgroundColor3 = Theme.Color.Panel,
		ZIndex = Theme.Layer.Hud,
	}, parent)
	Widgets.corner(Theme.Radius.Medium, panel)
	Widgets.stroke(Theme.Color.Stroke, 1, panel)

	waveLabel = Widgets.label({
		Text = "Wave: —",
		Size = UDim2.new(1, -16, 0, 26),
		Position = UDim2.fromOffset(12, 8),
		FontFace = Theme.Font.Heading,
		TextSize = 20,
	}, panel)

	enemyLabel = Widgets.label({
		Text = "Claiming a base…",
		Size = UDim2.new(1, -16, 0, 18),
		Position = UDim2.fromOffset(12, 32),
		TextSize = 13,
		TextColor3 = Theme.Color.TextMuted,
	}, panel)

	local track, fill = Widgets.progressBar(Theme.Color.Gem, panel)
	track.Size = UDim2.new(1, -24, 0, 8)
	track.Position = UDim2.fromOffset(12, 54)
	integrityFill = fill

	startButton = Widgets.button({
		Text = "START",
		Size = UDim2.fromOffset(120, 34),
		Position = UDim2.fromOffset(12, 68),
		Color = Theme.Color.Success,
		TextColor = Color3.fromRGB(14, 20, 16),
		OnClick = function()
			HudController.toggleWave()
		end,
	}, panel)

	autoButton = Widgets.button({
		Text = "Auto: Off",
		Size = UDim2.fromOffset(112, 34),
		Position = UDim2.fromOffset(138, 68),
		Color = Theme.Color.Raised,
		TextSize = 14,
		OnClick = function()
			HudController.toggleAuto()
		end,
	}, panel)

	for _, descendant in panel:GetDescendants() do
		if descendant:IsA("GuiObject") then
			descendant.ZIndex = Theme.Layer.Hud + 1
		end
	end
end

--------------------------------------------------------------------------------
-- Side navigation
--------------------------------------------------------------------------------

local NAV_BUTTONS = {
	{ Label = "ANIMES", Panel = "Inventory", Color = Color3.fromRGB(126, 106, 255) },
	{ Label = "SHOP", Panel = "Shop", Color = Color3.fromRGB(64, 170, 128) },
	{ Label = "UPGR.", Panel = "Upgrades", Color = Color3.fromRGB(72, 138, 210) },
	{ Label = "ITEMS", Panel = "Items", Color = Color3.fromRGB(210, 150, 66) },
	{ Label = "INDEX", Panel = "Index", Color = Color3.fromRGB(180, 96, 190) },
	{ Label = "CODES", Panel = "Codes", Color = Color3.fromRGB(96, 104, 132) },
}

local function buildNav(parent: Instance)
	local nav = Widgets.frame({
		Name = "Nav",
		Size = UDim2.fromOffset(104, #NAV_BUTTONS * 50),
		Position = UDim2.new(1, -120, 0.5, 0),
		AnchorPoint = Vector2.new(0, 0.5),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Hud,
	}, parent)

	Widgets.listLayout({ Padding = UDim.new(0, 8) }, nav)

	for order, entry in NAV_BUTTONS do
		local button = Widgets.button({
			Text = entry.Label,
			Size = UDim2.new(1, 0, 0, 42),
			Color = entry.Color,
			TextSize = 14,
			LayoutOrder = order,
			OnClick = function()
				PanelManager.toggle(entry.Panel)
			end,
		}, nav)
		button.ZIndex = Theme.Layer.Hud + 1
	end
end

--------------------------------------------------------------------------------
-- Roll button
--------------------------------------------------------------------------------

local function buildRollButton(parent: Instance)
	local holder = Widgets.frame({
		Name = "RollDock",
		Size = UDim2.fromOffset(240, 56),
		Position = UDim2.new(0.5, 0, 1, -24),
		AnchorPoint = Vector2.new(0.5, 1),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Hud,
	}, parent)

	local roll = Widgets.button({
		Text = "ROLL",
		Size = UDim2.fromOffset(240, 56),
		Color = Theme.Color.Accent,
		TextSize = 24,
		OnClick = function()
			PanelManager.open("Roll")
		end,
	}, holder)
	roll.ZIndex = Theme.Layer.Hud + 1
end

--------------------------------------------------------------------------------
-- Rare roll feed
--------------------------------------------------------------------------------

local function buildFeed(parent: Instance)
	feedFrame = Widgets.frame({
		Name = "Feed",
		Size = UDim2.fromOffset(300, 150),
		Position = UDim2.fromOffset(16, 130),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Hud,
	}, parent)
	Widgets.listLayout({ Padding = UDim.new(0, 4), VerticalAlignment = Enum.VerticalAlignment.Top }, feedFrame)
end

--[[
	Push a line into the rare-roll feed. Entries expire after 8 seconds; the feed
	keeps at most 5 so a burst of Mythics cannot cover the screen.
]]
function HudController.pushFeed(text: string, color: Color3)
	if not feedFrame then
		return
	end

	local children = feedFrame:GetChildren()
	local entries = {}
	for _, child in children do
		if child:IsA("Frame") then
			table.insert(entries, child)
		end
	end
	while #entries >= 5 do
		local oldest = table.remove(entries, 1)
		if oldest then
			oldest:Destroy()
		end
	end

	local row = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 26),
		BackgroundColor3 = Theme.Color.Panel,
		BackgroundTransparency = 0.15,
		ZIndex = Theme.Layer.Hud + 1,
		LayoutOrder = os.clock() * 1000 // 1,
	}, feedFrame)
	Widgets.corner(Theme.Radius.Small, row)
	Widgets.stroke(color, 1, row)

	Widgets.label({
		Text = text,
		Size = UDim2.new(1, -16, 1, 0),
		Position = UDim2.fromOffset(8, 0),
		TextSize = 13,
		TextColor3 = color,
		ZIndex = Theme.Layer.Hud + 2,
	}, row)

	task.delay(8, function()
		if row.Parent then
			TweenService:Create(row, Theme.Tween.Normal, { BackgroundTransparency = 1 }):Play()
			task.wait(0.25)
			row:Destroy()
		end
	end)
end

--------------------------------------------------------------------------------
-- Toasts
--------------------------------------------------------------------------------

local function buildToasts(parent: Instance)
	toastHolder = Widgets.frame({
		Name = "Toasts",
		Size = UDim2.fromOffset(380, 200),
		Position = UDim2.new(0.5, 0, 1, -100),
		AnchorPoint = Vector2.new(0.5, 1),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Toast,
	}, parent)

	Widgets.listLayout({
		Padding = UDim.new(0, 6),
		VerticalAlignment = Enum.VerticalAlignment.Bottom,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
	}, toastHolder)
end

function HudController.toast(kind: string, message: string)
	if not toastHolder then
		return
	end

	local color = Theme.Color.Accent
	if kind == "error" then
		color = Theme.Color.Danger
	elseif kind == "success" then
		color = Theme.Color.Success
	elseif kind == "info" then
		color = Theme.Color.Gem
	end

	local row = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 34),
		BackgroundColor3 = Theme.Color.Panel,
		ZIndex = Theme.Layer.Toast + 1,
		LayoutOrder = os.clock() * 1000 // 1,
	}, toastHolder)
	Widgets.corner(Theme.Radius.Medium, row)
	Widgets.stroke(color, 1.5, row)

	Widgets.label({
		Text = message,
		Size = UDim2.new(1, -20, 1, 0),
		Position = UDim2.fromOffset(10, 0),
		TextSize = 14,
		TextColor3 = color,
		TextXAlignment = Enum.TextXAlignment.Center,
		ZIndex = Theme.Layer.Toast + 2,
	}, row)

	task.delay(3.5, function()
		if row.Parent then
			TweenService:Create(row, Theme.Tween.Normal, { BackgroundTransparency = 1 }):Play()
			task.wait(0.25)
			row:Destroy()
		end
	end)
end

--------------------------------------------------------------------------------
-- Actions
--------------------------------------------------------------------------------

function HudController.toggleWave()
	local base = State.myBase()
	if not base then
		HudController.toast("error", "You don't have a base yet.")
		return
	end

	local result = if base.Running then State.request("StopWave") else State.request("StartWave")
	if not result.ok then
		HudController.toast("error", result.err or "Could not change the wave.")
	end
end

function HudController.toggleAuto()
	autoWaveOn = not autoWaveOn
	local result = State.request("SetAutoWave", autoWaveOn)
	if not result.ok then
		autoWaveOn = not autoWaveOn
		HudController.toast("error", result.err or "Could not toggle auto.")
		return
	end
	HudController.refresh()
end

--------------------------------------------------------------------------------
-- Refresh
--------------------------------------------------------------------------------

function HudController.refresh()
	local profile = State.profile
	if profile then
		goldLabel.Text = Format.abbreviate(profile.Gold)
		gemLabel.Text = Format.abbreviate(profile.Gems)

		local extra = profile.GoldMultiplier
		boostLabel.Text = if extra > 1 then `Gold x{string.format("%.2f", extra)}` else ""
	end

	local base = State.myBase()
	if base then
		waveLabel.Text = `Wave: {math.max(base.Wave, 1)}`
		if base.Running then
			enemyLabel.Text = `{base.EnemiesLeft}/{base.EnemiesTotal} enemies left`
			startButton.Text = "STOP"
			Widgets.setEnabled(startButton, true, Theme.Color.Danger)
		else
			enemyLabel.Text = `Base {base.Index} — ready`
			startButton.Text = "START"
			Widgets.setEnabled(startButton, true, Theme.Color.Success)
		end

		local ratio = if base.MaxIntegrity > 0 then base.Integrity / base.MaxIntegrity else 0
		integrityFill.Size = UDim2.fromScale(math.clamp(ratio, 0, 1), 1)
		integrityFill.BackgroundColor3 = if ratio > 0.5
			then Theme.Color.Gem
			elseif ratio > 0.25 then Theme.Color.Warning
			else Theme.Color.Danger
	else
		waveLabel.Text = "Wave: —"
		enemyLabel.Text = "Waiting for a free base…"
		startButton.Text = "START"
		Widgets.setEnabled(startButton, false, Theme.Color.Success)
		integrityFill.Size = UDim2.fromScale(0, 1)
	end

	autoButton.Text = if autoWaveOn then "Auto: On" else "Auto: Off"
	autoButton.BackgroundColor3 = if autoWaveOn then Theme.Color.Accent else Theme.Color.Raised
end

--------------------------------------------------------------------------------
-- Announcements
--------------------------------------------------------------------------------

function HudController.onAnnounce(kind: string, payload: { [string]: any })
	if kind == "RareRoll" then
		local unit = Units.get(payload.UnitId)
		local rarity = Rarities.get(payload.Rarity)
		local name = if unit then unit.Display else payload.UnitId
		local who = if payload.UserId == player.UserId then "You" else payload.PlayerName
		HudController.pushFeed(`{who} rolled <b>{name}</b> ({rarity.Display})!`, rarity.Color)
	elseif kind == "RareTrait" then
		local rarity = Rarities.get(payload.TraitRarity)
		local who = if payload.UserId == player.UserId then "You" else payload.PlayerName
		HudController.pushFeed(`{who} hit the <b>{payload.Trait}</b> trait!`, rarity.Color)
	elseif kind == "MutationEvent" then
		if payload.Active then
			State.mutationEventEndsAt = payload.EndsAt
			HudController.pushFeed(
				`<b>MUTATION EVENT</b> — x{payload.Multiplier} mutation odds!`,
				Theme.Color.Warning
			)
		else
			State.mutationEventEndsAt = 0
			HudController.pushFeed("Mutation event ended.", Theme.Color.TextMuted)
		end
	end
end

--------------------------------------------------------------------------------
-- Init
--------------------------------------------------------------------------------

function HudController.init(screen: ScreenGui)
	buildTopBar(screen)
	buildWavePanel(screen)
	buildNav(screen)
	buildRollButton(screen)
	buildFeed(screen)
	buildToasts(screen)

	State.on("profile", HudController.refresh)
	State.on("bases", HudController.refresh)

	HudController.refresh()
end

return HudController
