--!strict
--[[
	RateLimiter.luau

	Per-player, per-remote sliding-window limiter.

	Every remote handler runs through this. A client that exceeds its budget gets
	a refusal, not a disconnect — legitimate players can trip a limit by holding a
	button, and kicking them for it is worse than making them wait a moment.
]]

local Players = game:GetService("Players")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)

local RateLimiter = {}

type Window = { times: { number } }

local windows: { [Player]: { [string]: Window } } = {}

Players.PlayerRemoving:Connect(function(player)
	windows[player] = nil
end)

--[[
	Returns true when the call is allowed and records it. Unknown remote names
	fall back to GameConfig.RateLimits.Default.
]]
function RateLimiter.check(player: Player, remoteName: string): boolean
	local limit = GameConfig.RateLimits[remoteName] or GameConfig.RateLimits.Default
	local maxCalls, perSeconds = limit[1], limit[2]

	local playerWindows = windows[player]
	if not playerWindows then
		playerWindows = {}
		windows[player] = playerWindows
	end

	local window = playerWindows[remoteName]
	if not window then
		window = { times = {} }
		playerWindows[remoteName] = window
	end

	local now = os.clock()
	local cutoff = now - perSeconds

	-- Drop expired entries from the front.
	local kept: { number } = {}
	for _, timestamp in window.times do
		if timestamp > cutoff then
			table.insert(kept, timestamp)
		end
	end
	window.times = kept

	if #kept >= maxCalls then
		return false
	end

	table.insert(window.times, now)
	return true
end

return RateLimiter
