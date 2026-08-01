--!strict
--[[
	ShopController.luau

	The refreshable shop panel: six slots, a live countdown to the free refresh,
	and the escalating gold price for refreshing early.
]]

local RunService = game:GetService("RunService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Rarities = require(Shared.Config.Rarities)
local ShopConfig = require(Shared.Config.ShopConfig)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local ShopController = {}

local slotHolder: Frame
local timerLabel: TextLabel
local refreshButton: TextButton
local gemRefreshButton: TextButton
local countdownConnection: RBXScriptConnection? = nil

local function hud()
	return require(script.Parent.HudController)
end

--------------------------------------------------------------------------------
-- Slots
--------------------------------------------------------------------------------

local function buildSlot(slot: any, parent: Instance): Frame
	local unit = Units.expect(slot.UnitId)
	local rarity = Rarities.get(slot.Rarity)

	local card = Widgets.frame({
		Size = UDim2.fromOffset(132, 214),
		BackgroundColor3 = Theme.Color.PanelAlt,
		LayoutOrder = slot.Index,
	}, parent)
	Widgets.corner(Theme.Radius.Medium, card)
	Widgets.stroke(rarity.Color, 2, card)

	local inner = Widgets.unitCard({
		UnitId = slot.UnitId,
		Mutation = slot.Mutation,
		Footer = unit.Role,
		Dimmed = slot.SoldOut,
	}, card)
	inner.Position = UDim2.fromOffset(6, 6)
	inner.Size = UDim2.fromOffset(120, 150)
	inner.Active = false

	if slot.Discount > 0 and not slot.SoldOut then
		local tag = Widgets.frame({
			Size = UDim2.fromOffset(48, 18),
			Position = UDim2.fromOffset(6, 6),
			BackgroundColor3 = Theme.Color.Danger,
			ZIndex = 5,
		}, card)
		Widgets.corner(Theme.Radius.Pill, tag)
		Widgets.label({
			Text = `-{math.floor(slot.Discount * 100)}%`,
			Size = UDim2.fromScale(1, 1),
			TextSize = 11,
			FontFace = Theme.Font.Heading,
			TextXAlignment = Enum.TextXAlignment.Center,
			ZIndex = 6,
		}, tag)
	end

	local buy = Widgets.button({
		Text = if slot.SoldOut then "SOLD OUT" else Format.abbreviate(slot.Price),
		Size = UDim2.fromOffset(120, 42),
		Position = UDim2.fromOffset(6, 164),
		Color = if slot.SoldOut then Theme.Color.Raised else Theme.Color.Success,
		TextColor = if slot.SoldOut then Theme.Color.TextDim else Color3.fromRGB(12, 22, 16),
		TextSize = 15,
	}, card)

	local affordable = not slot.SoldOut and State.gold() >= slot.Price
	Widgets.setEnabled(buy, affordable, Theme.Color.Success)
	if slot.SoldOut then
		buy.Text = "SOLD OUT"
	end

	buy.Activated:Connect(function()
		if slot.SoldOut then
			return
		end
		local result = State.request("BuyShopSlot", slot.Index)
		if result.ok then
			hud().toast("success", `Bought {unit.Display}!`)
		else
			hud().toast("error", result.err or "Purchase failed.")
		end
	end)

	return card
end

--------------------------------------------------------------------------------
-- Panel
--------------------------------------------------------------------------------

local function build(content: Frame): () -> ()
	Widgets.label({
		Text = "Six slots. Refresh to reroll them all.",
		Size = UDim2.new(1, 0, 0, 20),
		TextSize = 14,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	timerLabel = Widgets.label({
		Text = "",
		Size = UDim2.new(1, 0, 0, 20),
		Position = UDim2.fromOffset(0, 22),
		TextSize = 14,
		TextColor3 = Theme.Color.Gem,
	}, content)

	slotHolder = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 460),
		Position = UDim2.fromOffset(0, 50),
		BackgroundTransparency = 1,
	}, content)
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(132, 214),
		CellPadding = UDim2.fromOffset(10, 10),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
	}, slotHolder)

	refreshButton = Widgets.button({
		Text = "REFRESH",
		Size = UDim2.new(0.6, -6, 0, 48),
		Position = UDim2.new(0, 0, 1, -54),
		Color = Theme.Color.Accent,
		OnClick = function()
			local result = State.request("RefreshShop", false)
			if not result.ok then
				hud().toast("error", result.err or "Refresh failed.")
			end
		end,
	}, content)

	gemRefreshButton = Widgets.button({
		Text = `💎 {ShopConfig.GemRefreshCost}`,
		Size = UDim2.new(0.4, -6, 0, 48),
		Position = UDim2.new(0.6, 6, 1, -54),
		Color = Theme.Color.Gem,
		TextColor = Color3.fromRGB(10, 24, 30),
		OnClick = function()
			local result = State.request("RefreshShop", true)
			if not result.ok then
				hud().toast("error", result.err or "Refresh failed.")
			end
		end,
	}, content)

	return ShopController.refresh
end

function ShopController.refresh()
	local shop = State.shop
	if not shop or not slotHolder then
		return
	end

	slotHolder:ClearAllChildren()
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(132, 214),
		CellPadding = UDim2.fromOffset(10, 10),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
	}, slotHolder)

	for _, slot in shop.Slots do
		buildSlot(slot, slotHolder)
	end

	local cost = shop.NextRefreshCost
	refreshButton.Text = `REFRESH — {Format.abbreviate(cost)}`
	Widgets.setEnabled(refreshButton, State.gold() >= cost, Theme.Color.Accent)
	Widgets.setEnabled(gemRefreshButton, State.gems() >= ShopConfig.GemRefreshCost, Theme.Color.Gem)
end

--------------------------------------------------------------------------------
-- Countdown
--------------------------------------------------------------------------------

--[[
	Tick the free-refresh countdown once a second while the panel is open. It is
	driven off the server's absolute timestamp rather than a local counter, so a
	client clock skew shows a wrong number for one second rather than drifting.
]]
local function startCountdown()
	if countdownConnection then
		return
	end

	local lastShown = -1
	countdownConnection = RunService.Heartbeat:Connect(function()
		if not PanelManager.isOpen("Shop") then
			return
		end
		local shop = State.shop
		if not shop or not timerLabel then
			return
		end

		local remaining = math.max(0, shop.NextFreeRefresh - os.time())
		if remaining == lastShown then
			return
		end
		lastShown = remaining

		if remaining > 0 then
			timerLabel.Text = `Free refresh in {Format.clock(remaining)}`
		else
			timerLabel.Text = "Free refresh ready!"
		end
	end)
end

function ShopController.init()
	PanelManager.register({
		Name = "Shop",
		Title = "SHOP",
		Size = UDim2.fromOffset(480, 620),
		Build = build,
	})

	State.on("shop", function()
		PanelManager.refreshIfOpen("Shop")
	end)
	State.on("profile", function()
		PanelManager.refreshIfOpen("Shop")
	end)

	startCountdown()
end

return ShopController
