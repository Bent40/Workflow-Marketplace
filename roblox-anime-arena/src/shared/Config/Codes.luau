--!strict
--[[
	Codes.luau

	Redeemable launch codes. Each code is one-shot per player; CodeService records
	redemptions on the profile.

	`Expires` is a unix timestamp, or nil for no expiry.
]]

export type CodeReward = {
	Gold: number?,
	Gems: number?,
	Items: { [string]: number }?,
	Rolls: number?,
}

export type Code = {
	Code: string,
	Reward: CodeReward,
	Expires: number?,
	Active: boolean,
}

local Codes = {}

-- Keys are stored uppercase; redemption uppercases the player's input.
Codes.Data = {
	RELEASE = {
		Code = "RELEASE",
		Reward = { Gold = 50000, Gems = 100 },
		Active = true,
	},
	ARENA = {
		Code = "ARENA",
		Reward = { Gold = 25000, Items = { TraitShard = 3 } },
		Active = true,
	},
	EIGHTBASES = {
		Code = "EIGHTBASES",
		Reward = { Gold = 80000, Rolls = 10 },
		Active = true,
	},
	LUCKY = {
		Code = "LUCKY",
		Reward = { Gems = 50, Items = { TraitShard = 5 } },
		Active = true,
	},
	THANKYOU = {
		Code = "THANKYOU",
		Reward = { Gold = 100000, Gems = 150, Items = { TraitShard = 10 } },
		Active = true,
	},
} :: { [string]: Code }

function Codes.get(raw: string): Code?
	local key = string.upper(string.gsub(raw, "%s", ""))
	local code = Codes.Data[key]
	if not code or not code.Active then
		return nil
	end
	if code.Expires and os.time() > code.Expires then
		return nil
	end
	return code
end

return Codes
