--!strict
--[[
	CollectionController.luau

	Three small panels that share the same shape, so they share a file:
	  INDEX  every unit in the game, owned ones lit and the rest greyed out
	  ITEMS  essence and shard counts
	  CODES  redemption box
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local GameConfig = require(Shared.Config.GameConfig)
local Items = require(Shared.Config.Items)
local Rarities = require(Shared.Config.Rarities)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local CollectionController = {}

local indexGrid: ScrollingFrame
local indexHeader: TextLabel
local itemGrid: ScrollingFrame
local codeInput: TextBox
local codeStatus: TextLabel

local function hud()
	return require(script.Parent.HudController)
end

--------------------------------------------------------------------------------
-- INDEX
--------------------------------------------------------------------------------

local function buildIndex(content: Frame): () -> ()
	indexHeader = Widgets.label({
		Text = "",
		Size = UDim2.new(1, 0, 0, 22),
		TextSize = 14,
		TextColor3 = Theme.Color.Success,
	}, content)

	indexGrid = Widgets.scroll({
		Size = UDim2.new(1, 0, 1, -28),
		Position = UDim2.fromOffset(0, 28),
	}, content)
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(110, 138),
		CellPadding = UDim2.fromOffset(8, 8),
	}, indexGrid)

	return CollectionController.refreshIndex
end

function CollectionController.refreshIndex()
	local profile = State.profile
	if not profile or not indexGrid then
		return
	end

	local owned: { [string]: boolean } = {}
	for _, unitId in profile.Index do
		owned[unitId] = true
	end

	local economy = GameConfig.Economy
	local tiers = #profile.Index // economy.IndexBonusPerUnits
	indexHeader.Text = string.format(
		"%d / %d collected  ·  +%d%% gold  (+%d%% per %d unique)",
		#profile.Index,
		Units.Count,
		math.floor(tiers * economy.IndexBonusAmount * 100),
		math.floor(economy.IndexBonusAmount * 100),
		economy.IndexBonusPerUnits
	)

	indexGrid:ClearAllChildren()
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(110, 138),
		CellPadding = UDim2.fromOffset(8, 8),
	}, indexGrid)

	for order, unitId in Units.All do
		local unit = Units.expect(unitId)
		local has = owned[unitId] == true

		local card = Widgets.unitCard({
			UnitId = unitId,
			Footer = if has then unit.Role else "???",
			Dimmed = not has,
		}, indexGrid)
		card.Size = UDim2.fromOffset(110, 138)
		card.LayoutOrder = order

		if not has then
			-- Hide the name of undiscovered units so the index is worth filling.
			local nameLabel = card:FindFirstChild("UnitName")
			if nameLabel and nameLabel:IsA("TextLabel") then
				nameLabel.Text = "???"
			end
		end
	end
end

--------------------------------------------------------------------------------
-- ITEMS
--------------------------------------------------------------------------------

local function buildItems(content: Frame): () -> ()
	Widgets.label({
		Text = "Essences and shards drop from kills.",
		Size = UDim2.new(1, 0, 0, 20),
		TextSize = 13,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	itemGrid = Widgets.scroll({
		Size = UDim2.new(1, 0, 1, -28),
		Position = UDim2.fromOffset(0, 28),
	}, content)
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(140, 96),
		CellPadding = UDim2.fromOffset(8, 8),
	}, itemGrid)

	return CollectionController.refreshItems
end

function CollectionController.refreshItems()
	local profile = State.profile
	if not profile or not itemGrid then
		return
	end

	itemGrid:ClearAllChildren()
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(140, 96),
		CellPadding = UDim2.fromOffset(8, 8),
	}, itemGrid)

	for order, item in Items.ordered() do
		local count = profile.Items[item.Id] or 0

		local card = Widgets.frame({
			BackgroundColor3 = Theme.Color.PanelAlt,
			LayoutOrder = order,
		}, itemGrid)
		Widgets.corner(Theme.Radius.Medium, card)
		Widgets.stroke(item.Color, 1.5, card)
		Widgets.padding(8, card)

		Widgets.label({
			Text = item.Display,
			Size = UDim2.new(1, 0, 0, 18),
			FontFace = Theme.Font.Heading,
			TextSize = 13,
			TextColor3 = item.Color,
			TextTruncate = Enum.TextTruncate.AtEnd,
		}, card)

		Widgets.label({
			Text = `x{Format.comma(count)}`,
			Size = UDim2.new(1, 0, 0, 26),
			Position = UDim2.fromOffset(0, 20),
			FontFace = Theme.Font.Numeric,
			TextSize = 20,
			TextColor3 = if count > 0 then Theme.Color.Text else Theme.Color.TextDim,
		}, card)

		Widgets.label({
			Text = item.Description,
			Size = UDim2.new(1, 0, 0, 30),
			Position = UDim2.fromOffset(0, 46),
			TextSize = 11,
			TextColor3 = Theme.Color.TextDim,
			TextWrapped = true,
		}, card)
	end
end

--------------------------------------------------------------------------------
-- CODES
--------------------------------------------------------------------------------

local function buildCodes(content: Frame): () -> ()
	Widgets.label({
		Text = "Enter a code for free rewards.",
		Size = UDim2.new(1, 0, 0, 22),
		TextSize = 14,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	local box = Instance.new("TextBox")
	box.Size = UDim2.new(1, 0, 0, 46)
	box.Position = UDim2.fromOffset(0, 30)
	box.BackgroundColor3 = Theme.Color.Backdrop
	box.BorderSizePixel = 0
	box.FontFace = Theme.Font.Body
	box.TextSize = 18
	box.TextColor3 = Theme.Color.Text
	box.PlaceholderText = "Type a code…"
	box.PlaceholderColor3 = Theme.Color.TextDim
	box.ClearTextOnFocus = false
	box.Text = ""
	box.Parent = content
	Widgets.corner(Theme.Radius.Medium, box)
	Widgets.stroke(Theme.Color.Stroke, 1, box)
	codeInput = box

	codeStatus = Widgets.label({
		Text = "",
		Size = UDim2.new(1, 0, 0, 40),
		Position = UDim2.fromOffset(0, 136),
		TextSize = 13,
		TextWrapped = true,
		TextXAlignment = Enum.TextXAlignment.Center,
	}, content)

	local function submit()
		local code = codeInput.Text
		if #code == 0 then
			return
		end

		local result = State.request("RedeemCode", code)
		if result.ok then
			codeStatus.TextColor3 = Theme.Color.Success
			codeStatus.Text = `Redeemed! You got {(result.data :: any).summary}.`
			codeInput.Text = ""
			hud().toast("success", "Code redeemed!")
		else
			codeStatus.TextColor3 = Theme.Color.Danger
			codeStatus.Text = result.err or "That code did not work."
		end
	end

	Widgets.button({
		Text = "REDEEM",
		Size = UDim2.new(1, 0, 0, 46),
		Position = UDim2.fromOffset(0, 84),
		Color = Theme.Color.Accent,
		OnClick = submit,
	}, content)

	box.FocusLost:Connect(function(enterPressed)
		if enterPressed then
			submit()
		end
	end)

	return function()
		codeStatus.Text = ""
	end
end

--------------------------------------------------------------------------------
-- Init
--------------------------------------------------------------------------------

function CollectionController.init()
	PanelManager.register({
		Name = "Index",
		Title = "INDEX",
		Size = UDim2.fromOffset(620, 540),
		Build = buildIndex,
	})

	PanelManager.register({
		Name = "Items",
		Title = "ITEMS",
		Size = UDim2.fromOffset(520, 460),
		Build = buildItems,
	})

	PanelManager.register({
		Name = "Codes",
		Title = "CODES",
		Size = UDim2.fromOffset(400, 320),
		Build = buildCodes,
	})

	State.on("profile", function()
		PanelManager.refreshIfOpen("Index")
		PanelManager.refreshIfOpen("Items")
	end)
end

-- Rarity legend helper, exposed for the index tooltip work later.
function CollectionController.rarityColor(rarityId: string): Color3
	return Rarities.color(rarityId :: any)
end

return CollectionController
