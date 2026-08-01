--!strict
--[[
	UpgradeController.luau

	The UPGR. panel: the four permanent gold sinks, each showing its current
	effect, next level and price.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Upgrades = require(Shared.Config.Upgrades)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local UpgradeController = {}

local holder: Frame

local function hud()
	return require(script.Parent.HudController)
end

local function buildRow(upgradeId: Upgrades.UpgradeId, order: number, parent: Instance)
	local profile = State.profile
	if not profile then
		return
	end

	local config = Upgrades.get(upgradeId)
	local level = profile.Upgrades[upgradeId] or 1
	local cost = Upgrades.costToNext(upgradeId, level)
	local maxed = cost == nil

	local row = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 92),
		BackgroundColor3 = Theme.Color.PanelAlt,
		LayoutOrder = order,
	}, parent)
	Widgets.corner(Theme.Radius.Medium, row)
	Widgets.padding(10, row)

	Widgets.label({
		Text = `{config.Icon}  {config.Display}`,
		Size = UDim2.new(1, -150, 0, 22),
		FontFace = Theme.Font.Heading,
		TextSize = 17,
	}, row)

	Widgets.label({
		Text = config.Description,
		Size = UDim2.new(1, -150, 0, 34),
		Position = UDim2.fromOffset(0, 24),
		TextSize = 12,
		TextColor3 = Theme.Color.TextMuted,
		TextWrapped = true,
	}, row)

	local currentEffect = Upgrades.formatEffect(upgradeId, level)
	local nextEffect = if maxed then currentEffect else Upgrades.formatEffect(upgradeId, level + 1)

	Widgets.label({
		Text = if maxed
			then `Lv. {level} (MAX) · {currentEffect}`
			else `Lv. {level} · {currentEffect} → {nextEffect}`,
		Size = UDim2.new(1, -150, 0, 20),
		Position = UDim2.fromOffset(0, 58),
		TextSize = 13,
		TextColor3 = Theme.Color.Success,
	}, row)

	local button = Widgets.button({
		Text = if maxed then "MAX" else Format.abbreviate(cost :: number),
		Size = UDim2.fromOffset(128, 44),
		Position = UDim2.new(1, -128, 0.5, -22),
		Color = Theme.Color.Gold,
		TextColor = Color3.fromRGB(28, 22, 8),
		TextSize = 16,
		OnClick = function()
			if maxed then
				return
			end
			local result = State.request("BuyUpgrade", upgradeId)
			if result.ok then
				hud().toast("success", `{config.Display} → Lv. {(result.data :: any).level}`)
			else
				hud().toast("error", result.err or "Upgrade failed.")
			end
		end,
	}, row)

	Widgets.setEnabled(button, not maxed and profile.Gold >= (cost or math.huge), Theme.Color.Gold)
end

local function build(content: Frame): () -> ()
	holder = Widgets.scroll({
		Size = UDim2.fromScale(1, 1),
	}, content)
	Widgets.listLayout({ Padding = UDim.new(0, 8) }, holder)

	return UpgradeController.refresh
end

function UpgradeController.refresh()
	if not holder then
		return
	end

	holder:ClearAllChildren()
	Widgets.listLayout({ Padding = UDim.new(0, 8) }, holder)

	for order, upgradeId in Upgrades.Order do
		buildRow(upgradeId, order, holder)
	end
end

function UpgradeController.init()
	PanelManager.register({
		Name = "Upgrades",
		Title = "UPGRADES",
		Size = UDim2.fromOffset(520, 470),
		Build = build,
	})

	State.on("profile", function()
		PanelManager.refreshIfOpen("Upgrades")
	end)
end

return UpgradeController
