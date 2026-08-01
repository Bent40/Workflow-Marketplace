--!strict
--[[
	Theme.luau

	Design tokens. Every colour, radius and font in the UI comes from here, so a
	restyle is one file rather than a sweep through every controller.
]]

local Theme = {}

Theme.Color = {
	-- Surfaces, darkest to lightest.
	Backdrop = Color3.fromRGB(10, 11, 18),
	Panel = Color3.fromRGB(22, 24, 36),
	PanelAlt = Color3.fromRGB(30, 33, 48),
	Raised = Color3.fromRGB(40, 44, 63),
	Stroke = Color3.fromRGB(58, 63, 88),

	Text = Color3.fromRGB(240, 243, 252),
	TextMuted = Color3.fromRGB(150, 158, 182),
	TextDim = Color3.fromRGB(104, 112, 136),

	Accent = Color3.fromRGB(126, 106, 255),
	AccentHover = Color3.fromRGB(148, 130, 255),

	Gold = Color3.fromRGB(255, 198, 72),
	Gem = Color3.fromRGB(96, 214, 255),

	Success = Color3.fromRGB(86, 214, 132),
	Danger = Color3.fromRGB(244, 92, 108),
	Warning = Color3.fromRGB(255, 176, 66),
}

Theme.Font = {
	Heading = Font.fromEnum(Enum.Font.GothamBold),
	Body = Font.fromEnum(Enum.Font.GothamMedium),
	Numeric = Font.fromEnum(Enum.Font.GothamBold),
}

Theme.Radius = {
	Small = UDim.new(0, 6),
	Medium = UDim.new(0, 10),
	Large = UDim.new(0, 16),
	Pill = UDim.new(1, 0),
}

Theme.Padding = {
	Tight = 6,
	Normal = 12,
	Loose = 20,
}

-- Z-order bands, so panels never fight over which is on top.
Theme.Layer = {
	World = 1,
	Hud = 10,
	Panel = 50,
	Overlay = 90,
	Toast = 120,
}

Theme.Tween = {
	Fast = TweenInfo.new(0.14, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
	Normal = TweenInfo.new(0.22, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
	Pop = TweenInfo.new(0.32, Enum.EasingStyle.Back, Enum.EasingDirection.Out),
}

return Theme
