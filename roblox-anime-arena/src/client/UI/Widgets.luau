--!strict
--[[
	Widgets.luau

	Small constructors for the handful of UI shapes this game repeats: panels,
	buttons, rarity-tinted unit cards, stat rows and toasts.

	No reactive framework here on purpose — the surface is small enough that
	explicit `refresh()` calls are easier to follow than a dependency graph, and
	the whole UI redraws off one snapshot push.
]]

local TweenService = game:GetService("TweenService")

local Theme = require(script.Parent.Theme)

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Mutations = require(Shared.Config.Mutations)
local Rarities = require(Shared.Config.Rarities)
local Traits = require(Shared.Config.Traits)
local Units = require(Shared.Config.Units)

local Widgets = {}

--------------------------------------------------------------------------------
-- Primitives
--------------------------------------------------------------------------------

function Widgets.corner(radius: UDim, parent: Instance): UICorner
	local corner = Instance.new("UICorner")
	corner.CornerRadius = radius
	corner.Parent = parent
	return corner
end

function Widgets.stroke(color: Color3?, thickness: number?, parent: Instance): UIStroke
	local stroke = Instance.new("UIStroke")
	stroke.Color = color or Theme.Color.Stroke
	stroke.Thickness = thickness or 1
	stroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	stroke.Parent = parent
	return stroke
end

function Widgets.padding(amount: number, parent: Instance): UIPadding
	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, amount)
	padding.PaddingBottom = UDim.new(0, amount)
	padding.PaddingLeft = UDim.new(0, amount)
	padding.PaddingRight = UDim.new(0, amount)
	padding.Parent = parent
	return padding
end

function Widgets.listLayout(props: { [string]: any }, parent: Instance): UIListLayout
	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, Theme.Padding.Tight)
	for key, value in props do
		(layout :: any)[key] = value
	end
	layout.Parent = parent
	return layout
end

function Widgets.gridLayout(props: { [string]: any }, parent: Instance): UIGridLayout
	local layout = Instance.new("UIGridLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.CellPadding = UDim2.fromOffset(8, 8)
	layout.CellSize = UDim2.fromOffset(120, 150)
	for key, value in props do
		(layout :: any)[key] = value
	end
	layout.Parent = parent
	return layout
end

--------------------------------------------------------------------------------
-- Text
--------------------------------------------------------------------------------

function Widgets.label(props: { [string]: any }, parent: Instance?): TextLabel
	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.FontFace = Theme.Font.Body
	label.TextColor3 = Theme.Color.Text
	label.TextSize = 16
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.RichText = true
	for key, value in props do
		(label :: any)[key] = value
	end
	label.Parent = parent
	return label
end

function Widgets.heading(text: string, parent: Instance?): TextLabel
	return Widgets.label({
		Text = text,
		FontFace = Theme.Font.Heading,
		TextSize = 22,
		Size = UDim2.new(1, 0, 0, 28),
	}, parent)
end

--------------------------------------------------------------------------------
-- Containers
--------------------------------------------------------------------------------

function Widgets.frame(props: { [string]: any }, parent: Instance?): Frame
	local frame = Instance.new("Frame")
	frame.BackgroundColor3 = Theme.Color.Panel
	frame.BorderSizePixel = 0
	for key, value in props do
		(frame :: any)[key] = value
	end
	frame.Parent = parent
	return frame
end

function Widgets.scroll(props: { [string]: any }, parent: Instance?): ScrollingFrame
	local scroll = Instance.new("ScrollingFrame")
	scroll.BackgroundTransparency = 1
	scroll.BorderSizePixel = 0
	scroll.ScrollBarThickness = 5
	scroll.ScrollBarImageColor3 = Theme.Color.Stroke
	scroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
	scroll.CanvasSize = UDim2.new()
	for key, value in props do
		(scroll :: any)[key] = value
	end
	scroll.Parent = parent
	return scroll
end

--------------------------------------------------------------------------------
-- Buttons
--------------------------------------------------------------------------------

export type ButtonOptions = {
	Text: string,
	Size: UDim2?,
	Position: UDim2?,
	AnchorPoint: Vector2?,
	Color: Color3?,
	TextColor: Color3?,
	TextSize: number?,
	LayoutOrder: number?,
	OnClick: (() -> ())?,
}

function Widgets.button(options: ButtonOptions, parent: Instance?): TextButton
	local base = options.Color or Theme.Color.Accent

	local button = Instance.new("TextButton")
	button.Text = options.Text
	button.Size = options.Size or UDim2.new(1, 0, 0, 40)
	button.Position = options.Position or UDim2.new()
	button.AnchorPoint = options.AnchorPoint or Vector2.new()
	button.BackgroundColor3 = base
	button.BorderSizePixel = 0
	button.AutoButtonColor = false
	button.FontFace = Theme.Font.Heading
	button.TextSize = options.TextSize or 17
	button.TextColor3 = options.TextColor or Theme.Color.Text
	button.LayoutOrder = options.LayoutOrder or 0
	button.Parent = parent

	Widgets.corner(Theme.Radius.Medium, button)

	-- Hover/press feedback. Lightening by a fixed ratio keeps every button in the
	-- palette consistent regardless of its base colour.
	local function tint(factor: number)
		TweenService:Create(button, Theme.Tween.Fast, {
			BackgroundColor3 = base:Lerp(Color3.new(1, 1, 1), factor),
		}):Play()
	end

	button.MouseEnter:Connect(function()
		tint(0.12)
	end)
	button.MouseLeave:Connect(function()
		tint(0)
	end)
	button.MouseButton1Down:Connect(function()
		-- Darken on press; tint() only lightens, so this one is written out.
		TweenService:Create(button, Theme.Tween.Fast, { BackgroundColor3 = base:Lerp(Color3.new(), 0.2) }):Play()
	end)
	button.MouseButton1Up:Connect(function()
		tint(0.12)
	end)

	if options.OnClick then
		button.Activated:Connect(options.OnClick)
	end

	return button
end

-- Sets a button into a disabled look and blocks its click handler.
function Widgets.setEnabled(button: TextButton, enabled: boolean, baseColor: Color3)
	button.Active = enabled
	button.AutoButtonColor = false
	button.BackgroundColor3 = if enabled then baseColor else Theme.Color.Raised
	button.TextColor3 = if enabled then Theme.Color.Text else Theme.Color.TextDim
end

--------------------------------------------------------------------------------
-- Currency pill
--------------------------------------------------------------------------------

function Widgets.currencyPill(icon: string, color: Color3, parent: Instance?): (Frame, TextLabel)
	local pill = Widgets.frame({
		Size = UDim2.fromOffset(168, 38),
		BackgroundColor3 = Theme.Color.Panel,
	}, parent)
	Widgets.corner(Theme.Radius.Pill, pill)
	Widgets.stroke(Theme.Color.Stroke, 1, pill)

	Widgets.label({
		Text = icon,
		Size = UDim2.fromOffset(30, 38),
		Position = UDim2.fromOffset(8, 0),
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Center,
	}, pill)

	local value = Widgets.label({
		Name = "Value",
		Text = "0",
		Size = UDim2.new(1, -46, 1, 0),
		Position = UDim2.fromOffset(40, 0),
		FontFace = Theme.Font.Numeric,
		TextColor3 = color,
		TextSize = 17,
	}, pill)

	return pill, value
end

--------------------------------------------------------------------------------
-- Unit card
--------------------------------------------------------------------------------

export type UnitCardData = {
	UnitId: string,
	Level: number?,
	Trait: string?,
	Mutation: string?,
	Footer: string?,
	Dimmed: boolean?,
}

--[[
	The card used in the inventory grid, the shop, the index and the roll reveal.
	Rarity drives the border and the header tint; mutation drives the body tint.
]]
function Widgets.unitCard(data: UnitCardData, parent: Instance?): TextButton
	local unit = Units.expect(data.UnitId)
	local rarity = Rarities.get(unit.Rarity)
	local mutation = Mutations.get(data.Mutation)

	local card = Instance.new("TextButton")
	card.Text = ""
	card.AutoButtonColor = false
	card.BackgroundColor3 = Theme.Color.PanelAlt
	card.BorderSizePixel = 0
	card.Size = UDim2.fromOffset(120, 150)
	card.Parent = parent

	Widgets.corner(Theme.Radius.Medium, card)
	local stroke = Widgets.stroke(rarity.Color, 2, card)
	stroke.Transparency = if data.Dimmed then 0.6 else 0

	-- Rarity banner.
	local banner = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 20),
		BackgroundColor3 = rarity.Color,
	}, card)
	Widgets.corner(Theme.Radius.Medium, banner)
	Widgets.label({
		Text = rarity.Display,
		Size = UDim2.fromScale(1, 1),
		FontFace = Theme.Font.Heading,
		TextSize = 12,
		TextColor3 = Color3.fromRGB(16, 16, 22),
		TextXAlignment = Enum.TextXAlignment.Center,
	}, banner)

	-- Portrait stand-in. Replace with a ViewportFrame of the unit model, or a
	-- decal, once art exists; the card layout does not change.
	local portrait = Widgets.frame({
		Size = UDim2.new(1, -16, 0, 62),
		Position = UDim2.fromOffset(8, 26),
		BackgroundColor3 = if mutation.Id == "None" then unit.Color else mutation.Color,
	}, card)
	Widgets.corner(Theme.Radius.Small, portrait)
	Widgets.label({
		Text = string.sub(unit.Display, 1, 1),
		Size = UDim2.fromScale(1, 1),
		FontFace = Theme.Font.Heading,
		TextSize = 30,
		TextColor3 = Color3.fromRGB(20, 20, 28),
		TextXAlignment = Enum.TextXAlignment.Center,
	}, portrait)

	if mutation.Id ~= "None" then
		local tag = Widgets.frame({
			Size = UDim2.fromOffset(52, 16),
			Position = UDim2.new(1, -58, 0, 30),
			BackgroundColor3 = mutation.Color,
		}, card)
		Widgets.corner(Theme.Radius.Pill, tag)
		Widgets.label({
			Text = mutation.Display,
			Size = UDim2.fromScale(1, 1),
			TextSize = 10,
			FontFace = Theme.Font.Heading,
			TextColor3 = Color3.fromRGB(18, 18, 24),
			TextXAlignment = Enum.TextXAlignment.Center,
		}, tag)
	end

	Widgets.label({
		Name = "UnitName",
		Text = unit.Display,
		Size = UDim2.new(1, -12, 0, 16),
		Position = UDim2.fromOffset(6, 92),
		TextSize = 13,
		FontFace = Theme.Font.Heading,
		TextTruncate = Enum.TextTruncate.AtEnd,
	}, card)

	local traitId = data.Trait
	if traitId and traitId ~= "None" then
		local trait = Traits.get(traitId)
		Widgets.label({
			Name = "Trait",
			Text = trait.Display,
			Size = UDim2.new(1, -12, 0, 14),
			Position = UDim2.fromOffset(6, 108),
			TextSize = 11,
			TextColor3 = Rarities.color(trait.Rarity),
		}, card)
	end

	Widgets.label({
		Name = "Footer",
		Text = data.Footer or (if data.Level then `Lv. {data.Level}` else ""),
		Size = UDim2.new(1, -12, 0, 16),
		Position = UDim2.fromOffset(6, 126),
		TextSize = 12,
		TextColor3 = Theme.Color.TextMuted,
	}, card)

	if data.Dimmed then
		card.BackgroundColor3 = Theme.Color.Panel
		for _, descendant in card:GetDescendants() do
			if descendant:IsA("TextLabel") then
				descendant.TextTransparency = 0.5
			elseif descendant:IsA("Frame") then
				descendant.BackgroundTransparency = 0.5
			end
		end
	end

	return card
end

--------------------------------------------------------------------------------
-- Stat rows
--------------------------------------------------------------------------------

function Widgets.statRow(name: string, value: string, color: Color3?, parent: Instance?): Frame
	local row = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 22),
		BackgroundTransparency = 1,
	}, parent)

	Widgets.label({
		Text = name,
		Size = UDim2.fromScale(0.55, 1),
		TextSize = 14,
		TextColor3 = Theme.Color.TextMuted,
	}, row)

	Widgets.label({
		Text = value,
		Size = UDim2.fromScale(0.45, 1),
		Position = UDim2.fromScale(0.55, 0),
		TextSize = 14,
		FontFace = Theme.Font.Numeric,
		TextColor3 = color or Theme.Color.Text,
		TextXAlignment = Enum.TextXAlignment.Right,
	}, row)

	return row
end

--------------------------------------------------------------------------------
-- Progress bar
--------------------------------------------------------------------------------

function Widgets.progressBar(color: Color3, parent: Instance?): (Frame, Frame)
	local track = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 10),
		BackgroundColor3 = Theme.Color.Backdrop,
	}, parent)
	Widgets.corner(Theme.Radius.Pill, track)

	local fill = Widgets.frame({
		Name = "Fill",
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = color,
	}, track)
	Widgets.corner(Theme.Radius.Pill, fill)

	return track, fill
end

--------------------------------------------------------------------------------
-- Formatting passthroughs, so controllers only import Widgets
--------------------------------------------------------------------------------

Widgets.abbreviate = Format.abbreviate
Widgets.comma = Format.comma
Widgets.clock = Format.clock

return Widgets
