--!strict
--[[
	MutationEventService.luau

	Server-wide Mutation Events. Every GameConfig.MutationEvent.IntervalSeconds a
	window opens during which non-None mutation weights are multiplied, then it
	closes again. Announced to everyone so it reads as an event worth staying for.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local GameConfig = require(Shared.Config.GameConfig)

local RollService = require(script.Parent.RollService)
local SyncService = require(script.Parent.SyncService)

local MutationEventService = {}

local endsAt = 0

function MutationEventService.isActive(): boolean
	return os.time() < endsAt
end

function MutationEventService.endsAt(): number
	return endsAt
end

function MutationEventService.start()
	task.spawn(function()
		local config = GameConfig.MutationEvent
		while true do
			task.wait(config.IntervalSeconds - config.DurationSeconds)

			endsAt = os.time() + config.DurationSeconds
			RollService.setMutationEvent(true)
			SyncService.announce("MutationEvent", {
				Active = true,
				EndsAt = endsAt,
				Multiplier = config.WeightMultiplier,
			})

			task.wait(config.DurationSeconds)

			endsAt = 0
			RollService.setMutationEvent(false)
			SyncService.announce("MutationEvent", { Active = false, EndsAt = 0 })
		end
	end)
end

return MutationEventService
