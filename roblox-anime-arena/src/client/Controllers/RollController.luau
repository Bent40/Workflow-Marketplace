--!strict
--[[
	RollController.luau

	The summon screen: odds, pity counters, x1 / x10 buttons and the reveal.

	The reveal is pure theatre. The server already rolled, granted and saved
	before the client sees anything, so nothing here can change an outcome — it
	just controls how quickly the player finds out.
]]

local TweenService = game:GetService("TweenService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local GameConfig = require(Shared.Config.GameConfig)
local Rarities = require(Shared.Config.Rarities)
local Types = require(Shared.Types)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local RollController = {}

local oddsHolder: Frame
local pityHolder: Frame
local rollOneButton: TextButton
local rollTenButton: TextButton
local luckLabel: TextLabel

local revealGui: ScreenGui? = nil
local rolling = false

--------------------------------------------------------------------------------
-- Reveal overlay
--------------------------------------------------------------------------------

local function ensureRevealGui(parent: Instance): ScreenGui
	if revealGui and revealGui.Parent then
		return revealGui
	end

	local gui = Instance.new("ScreenGui")
	gui.Name = "RollReveal"
	gui.ResetOnSpawn = false
	gui.IgnoreGuiInset = true
	gui.DisplayOrder = Theme.Layer.Overlay
	gui.Enabled = false
	gui.Parent = parent

	revealGui = gui
	return gui
end

--[[
	Show the results. Cards fade in one at a time, fastest for a x10 so the whole
	sequence stays under about a second and a half.
]]
local function playReveal(results: { Types.RollResult })
	local gui = revealGui
	if not gui then
		return
	end

	for _, child in gui:GetChildren() do
		child:Destroy()
	end

	local shade = Widgets.frame({
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Theme.Color.Backdrop,
		BackgroundTransparency = 1,
	}, gui)

	local holder = Widgets.frame({
		Size = UDim2.new(0, 1, 0, 200),
		Position = UDim2.fromScale(0.5, 0.45),
		AnchorPoint = Vector2.new(0.5, 0.5),
		BackgroundTransparency = 1,
		AutomaticSize = Enum.AutomaticSize.X,
	}, shade)

	Widgets.listLayout({
		FillDirection = Enum.FillDirection.Horizontal,
		Padding = UDim.new(0, 10),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		VerticalAlignment = Enum.VerticalAlignment.Center,
	}, holder)

	local dismiss = Widgets.button({
		Text = "Tap to continue",
		Size = UDim2.fromOffset(220, 44),
		Position = UDim2.fromScale(0.5, 0.78),
		AnchorPoint = Vector2.new(0.5, 0.5),
		Color = Theme.Color.Raised,
		TextSize = 16,
		OnClick = function()
			gui.Enabled = false
		end,
	}, shade)
	dismiss.Visible = false

	gui.Enabled = true
	TweenService:Create(shade, Theme.Tween.Normal, { BackgroundTransparency = 0.25 }):Play()

	local stagger = if #results > 1 then 0.09 else 0.25

	task.spawn(function()
		for order, result in results do
			local card = Widgets.unitCard({
				UnitId = result.UnitId,
				Trait = result.Trait,
				Mutation = result.Mutation,
				Footer = if result.Kept then (if result.Pitied then "PITY!" else "NEW") else "LOST — full!",
			}, holder)
			card.LayoutOrder = order
			card.Size = UDim2.fromOffset(0, 0)

			TweenService:Create(card, Theme.Tween.Pop, { Size = UDim2.fromOffset(120, 150) }):Play()
			task.wait(stagger)
		end

		dismiss.Visible = true
		-- Auto-dismiss so a player spamming x10 is never blocked by the overlay.
		task.wait(2.2)
		if gui.Enabled then
			gui.Enabled = false
		end
	end)
end

--------------------------------------------------------------------------------
-- Rolling
--------------------------------------------------------------------------------

local function doRoll(count: number, currency: string)
	if rolling then
		return
	end
	rolling = true

	Widgets.setEnabled(rollOneButton, false, Theme.Color.Accent)
	Widgets.setEnabled(rollTenButton, false, Theme.Color.Gold)

	local result = State.request("Roll", count, currency)

	rolling = false
	RollController.refresh()

	if not result.ok then
		local HudController = require(script.Parent.HudController)
		HudController.toast("error", result.err or "Roll failed.")
		return
	end

	local rolls = result.data :: { Types.RollResult }?
	if rolls and #rolls > 0 then
		playReveal(rolls)
	end
end

--------------------------------------------------------------------------------
-- Panel
--------------------------------------------------------------------------------

local function build(content: Frame): () -> ()
	luckLabel = Widgets.label({
		Text = "Luck x1.0",
		Size = UDim2.new(1, 0, 0, 22),
		FontFace = Theme.Font.Heading,
		TextSize = 17,
		TextColor3 = Theme.Color.Success,
	}, content)

	Widgets.label({
		Text = "Odds at your current luck",
		Size = UDim2.new(1, 0, 0, 18),
		Position = UDim2.fromOffset(0, 26),
		TextSize = 13,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	oddsHolder = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 172),
		Position = UDim2.fromOffset(0, 48),
		BackgroundTransparency = 1,
	}, content)
	Widgets.listLayout({ Padding = UDim.new(0, 2) }, oddsHolder)

	Widgets.label({
		Text = "Guaranteed in",
		Size = UDim2.new(1, 0, 0, 18),
		Position = UDim2.fromOffset(0, 228),
		TextSize = 13,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	pityHolder = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 96),
		Position = UDim2.fromOffset(0, 250),
		BackgroundTransparency = 1,
	}, content)
	Widgets.listLayout({ Padding = UDim.new(0, 2) }, pityHolder)

	rollOneButton = Widgets.button({
		Text = "SUMMON",
		Size = UDim2.new(0.48, 0, 0, 52),
		Position = UDim2.new(0, 0, 1, -58),
		Color = Theme.Color.Accent,
		TextSize = 18,
		OnClick = function()
			doRoll(1, "Gold")
		end,
	}, content)

	rollTenButton = Widgets.button({
		Text = "SUMMON x10",
		Size = UDim2.new(0.48, 0, 0, 52),
		Position = UDim2.new(0.52, 0, 1, -58),
		Color = Theme.Color.Gold,
		TextColor = Color3.fromRGB(28, 22, 8),
		TextSize = 18,
		OnClick = function()
			doRoll(GameConfig.Roll.MultiCount, "Gold")
		end,
	}, content)

	return RollController.refresh
end

--------------------------------------------------------------------------------
-- Refresh
--------------------------------------------------------------------------------

--[[
	Recompute the displayed odds locally.

	This duplicates the server's weighting, which is a real risk of drift — but
	both read the same Rarities.weightAtLuck, so the only way they can disagree is
	if the server applies a luck source the snapshot does not expose. That is why
	the snapshot ships the final `Luck` number rather than the upgrade level.
]]
function RollController.refresh()
	local profile = State.profile
	if not profile or not oddsHolder then
		return
	end

	luckLabel.Text = `Luck x{string.format("%.1f", profile.Luck)}`

	oddsHolder:ClearAllChildren()
	Widgets.listLayout({ Padding = UDim.new(0, 2) }, oddsHolder)

	local total = 0
	local weights: { [string]: number } = {}
	for _, id in Rarities.Order do
		local weight = Rarities.weightAtLuck(id, profile.Luck)
		weights[id] = weight
		total += weight
	end

	for order, id in Rarities.Order do
		local rarity = Rarities.get(id)
		local chance = weights[id] / total
		local row = Widgets.statRow(rarity.Display, Format.percent(chance, 3), rarity.Color, oddsHolder)
		row.LayoutOrder = order
	end

	pityHolder:ClearAllChildren()
	Widgets.listLayout({ Padding = UDim.new(0, 2) }, pityHolder)

	for order, tier in Rarities.PityOrder do
		local threshold = Rarities.Pity[tier]
		if threshold then
			local seen = profile.Pity[tier] or 0
			local remaining = math.max(0, threshold - seen)
			local row = Widgets.statRow(
				Rarities.get(tier).Display,
				`{remaining} rolls`,
				Rarities.color(tier),
				pityHolder
			)
			row.LayoutOrder = order
		end
	end

	local singleCost = GameConfig.Roll.GoldCost
	local multiCost = math.floor(singleCost * GameConfig.Roll.MultiCount * (1 - GameConfig.Roll.MultiDiscount) + 0.5)

	rollOneButton.Text = `SUMMON\n{Format.abbreviate(singleCost)}`
	rollTenButton.Text = `SUMMON x{GameConfig.Roll.MultiCount}\n{Format.abbreviate(multiCost)}`

	Widgets.setEnabled(rollOneButton, profile.Gold >= singleCost and not rolling, Theme.Color.Accent)
	Widgets.setEnabled(rollTenButton, profile.Gold >= multiCost and not rolling, Theme.Color.Gold)
end

function RollController.init(screen: ScreenGui)
	ensureRevealGui(screen.Parent :: Instance)

	PanelManager.register({
		Name = "Roll",
		Title = "SUMMON",
		Size = UDim2.fromOffset(420, 520),
		Build = build,
	})

	State.on("profile", function()
		PanelManager.refreshIfOpen("Roll")
	end)
end

return RollController
