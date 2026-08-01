--!strict
--[[
	Format.luau

	Display helpers. Gold values run to the billions by the late game, so the HUD
	abbreviates while tooltips show the exact figure.
]]

local Format = {}

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc" }

-- 1234567 -> "1.23M"
function Format.abbreviate(value: number): string
	if value ~= value then -- NaN guard
		return "0"
	end
	local negative = value < 0
	local n = math.abs(value)

	if n < 1000 then
		local rounded = math.floor(n + 0.5)
		return (if negative then "-" else "") .. tostring(rounded)
	end

	local tier = math.min(math.floor(math.log(n, 1000)), #SUFFIXES - 1)
	local scaled = n / 1000 ^ tier

	local text: string
	if scaled >= 100 then
		text = string.format("%.0f", scaled)
	elseif scaled >= 10 then
		text = string.format("%.1f", scaled)
	else
		text = string.format("%.2f", scaled)
	end

	-- Trim trailing zeros so we get "1.2M" instead of "1.20M".
	text = string.gsub(text, "%.?0+$", "")
	return (if negative then "-" else "") .. text .. SUFFIXES[tier + 1]
end

-- 1234567 -> "1,234,567"
function Format.comma(value: number): string
	local negative = value < 0
	local text = tostring(math.floor(math.abs(value) + 0.5))
	local out = ""
	local count = 0
	for i = #text, 1, -1 do
		out = string.sub(text, i, i) .. out
		count += 1
		if count % 3 == 0 and i > 1 then
			out = "," .. out
		end
	end
	return (if negative then "-" else "") .. out
end

-- 3725 -> "01:02:05"
function Format.clock(seconds: number): string
	local n = math.max(0, math.floor(seconds))
	local hours = n // 3600
	local minutes = (n % 3600) // 60
	local secs = n % 60
	if hours > 0 then
		return string.format("%02d:%02d:%02d", hours, minutes, secs)
	end
	return string.format("%02d:%02d", minutes, secs)
end

-- 0.0234 -> "2.34%"
function Format.percent(fraction: number, decimals: number?): string
	return string.format(`%.{decimals or 2}f%%`, fraction * 100)
end

-- "1 in 4,210"
function Format.odds(fraction: number): string
	if fraction <= 0 then
		return "—"
	end
	return `1 in {Format.comma(1 / fraction)}`
end

return Format
