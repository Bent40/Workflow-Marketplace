--!strict
--[[
	PanelManager.luau

	One modal panel open at a time. Panels register a builder; the manager owns
	showing, hiding and the shared chrome (backdrop, title bar, close button).

	Panels are built lazily on first open and then kept, because rebuilding the
	inventory grid every time the player toggles it is the one place this UI would
	visibly hitch.
]]

local TweenService = game:GetService("TweenService")

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)

local PanelManager = {}

export type Panel = {
	Name: string,
	Title: string,
	Size: UDim2,
	-- Called once, with the content frame. Return a refresh function.
	Build: (Frame) -> (() -> ())?,
}

type Registered = {
	Config: Panel,
	Root: Frame?,
	Refresh: (() -> ())?,
}

local screen: ScreenGui? = nil
local backdrop: TextButton? = nil
local panels: { [string]: Registered } = {}
local openName: string? = nil

function PanelManager.init(parent: ScreenGui)
	screen = parent

	local shade = Instance.new("TextButton")
	shade.Name = "PanelBackdrop"
	shade.Text = ""
	shade.AutoButtonColor = false
	shade.Size = UDim2.fromScale(1, 1)
	shade.BackgroundColor3 = Theme.Color.Backdrop
	shade.BackgroundTransparency = 1
	shade.BorderSizePixel = 0
	shade.Visible = false
	shade.ZIndex = Theme.Layer.Panel
	shade.Parent = parent

	-- Clicking outside the panel closes it.
	shade.Activated:Connect(function()
		PanelManager.close()
	end)

	backdrop = shade
end

function PanelManager.register(config: Panel)
	panels[config.Name] = { Config = config, Root = nil, Refresh = nil }
end

local function buildPanel(entry: Registered): Frame
	local config = entry.Config
	assert(screen, "PanelManager.init must run before a panel is opened")

	local root = Widgets.frame({
		Name = config.Name,
		Size = config.Size,
		Position = UDim2.fromScale(0.5, 0.5),
		AnchorPoint = Vector2.new(0.5, 0.5),
		BackgroundColor3 = Theme.Color.Panel,
		Visible = false,
		ZIndex = Theme.Layer.Panel + 1,
	}, screen)
	Widgets.corner(Theme.Radius.Large, root)
	Widgets.stroke(Theme.Color.Stroke, 1.5, root)

	-- Title bar.
	local header = Widgets.frame({
		Name = "Header",
		Size = UDim2.new(1, 0, 0, 48),
		BackgroundColor3 = Theme.Color.PanelAlt,
		ZIndex = Theme.Layer.Panel + 2,
	}, root)
	Widgets.corner(Theme.Radius.Large, header)

	Widgets.label({
		Text = config.Title,
		Size = UDim2.new(1, -70, 1, 0),
		Position = UDim2.fromOffset(18, 0),
		FontFace = Theme.Font.Heading,
		TextSize = 20,
		ZIndex = Theme.Layer.Panel + 3,
	}, header)

	local close = Widgets.button({
		Text = "✕",
		Size = UDim2.fromOffset(34, 34),
		Position = UDim2.new(1, -44, 0, 7),
		Color = Theme.Color.Raised,
		TextSize = 18,
		OnClick = function()
			PanelManager.close()
		end,
	}, header)
	close.ZIndex = Theme.Layer.Panel + 3

	local content = Widgets.frame({
		Name = "Content",
		Size = UDim2.new(1, 0, 1, -48),
		Position = UDim2.fromOffset(0, 48),
		BackgroundTransparency = 1,
		ZIndex = Theme.Layer.Panel + 2,
	}, root)
	Widgets.padding(Theme.Padding.Normal, content)

	entry.Root = root
	entry.Refresh = config.Build(content)

	return root
end

function PanelManager.isOpen(name: string?): boolean
	if name then
		return openName == name
	end
	return openName ~= nil
end

function PanelManager.close()
	if not openName then
		return
	end

	local entry = panels[openName]
	if entry and entry.Root then
		entry.Root.Visible = false
	end
	if backdrop then
		backdrop.Visible = false
		backdrop.BackgroundTransparency = 1
	end
	openName = nil
end

function PanelManager.open(name: string)
	local entry = panels[name]
	if not entry then
		warn(`[PanelManager] no panel registered as "{name}"`)
		return
	end

	if openName == name then
		PanelManager.close()
		return
	end

	PanelManager.close()

	local root = entry.Root or buildPanel(entry)

	if entry.Refresh then
		local ok, err = pcall(entry.Refresh)
		if not ok then
			warn(`[PanelManager] refresh for "{name}" errored: {err}`)
		end
	end

	if backdrop then
		backdrop.Visible = true
		TweenService:Create(backdrop, Theme.Tween.Normal, { BackgroundTransparency = 0.45 }):Play()
	end

	root.Visible = true
	-- A small pop so opening reads as deliberate rather than instant.
	root.Size = UDim2.new(
		entry.Config.Size.X.Scale * 0.96,
		entry.Config.Size.X.Offset * 0.96,
		entry.Config.Size.Y.Scale * 0.96,
		entry.Config.Size.Y.Offset * 0.96
	)
	TweenService:Create(root, Theme.Tween.Pop, { Size = entry.Config.Size }):Play()

	openName = name
end

function PanelManager.toggle(name: string)
	if openName == name then
		PanelManager.close()
	else
		PanelManager.open(name)
	end
end

-- Refresh a panel if (and only if) it is currently visible.
function PanelManager.refreshIfOpen(name: string)
	if openName ~= name then
		return
	end
	local entry = panels[name]
	if entry and entry.Refresh then
		local ok, err = pcall(entry.Refresh)
		if not ok then
			warn(`[PanelManager] refresh for "{name}" errored: {err}`)
		end
	end
end

-- Refresh every built panel that is open. Called on each profile push.
function PanelManager.refreshOpen()
	if openName then
		PanelManager.refreshIfOpen(openName)
	end
end

return PanelManager
