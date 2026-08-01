--!strict
--[[
	CodeService.luau

	Redeemable codes. One redemption per player per code, recorded on the profile.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Codes = require(Shared.Config.Codes)
local GameConfig = require(Shared.Config.GameConfig)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local CodeService = {}

function CodeService.redeem(player: Player, profile: Profile, raw: string): Types.Result<{ summary: string }>
	if type(raw) ~= "string" or #raw == 0 or #raw > 40 then
		return { ok = false, err = "Enter a code." }
	end

	local key = string.upper(string.gsub(raw, "%s", ""))
	if profile.RedeemedCodes[key] then
		return { ok = false, err = "You already redeemed that code." }
	end

	local code = Codes.get(raw)
	if not code then
		return { ok = false, err = "Invalid or expired code." }
	end

	-- Mark before granting so a mid-grant error cannot leave the code re-usable.
	profile.RedeemedCodes[key] = true

	local parts: { string } = {}
	local reward = code.Reward

	if reward.Gold then
		CurrencyService.addGold(player, profile, reward.Gold)
		table.insert(parts, `{reward.Gold} Gold`)
	end
	if reward.Gems then
		CurrencyService.addGems(player, profile, reward.Gems)
		table.insert(parts, `{reward.Gems} Gems`)
	end
	if reward.Items then
		CurrencyService.addItems(player, profile, reward.Items)
		for itemId, amount in reward.Items do
			table.insert(parts, `{amount}x {itemId}`)
		end
	end
	if reward.Rolls then
		-- Free rolls are paid out as the gold they would have cost, so the reward
		-- has a single code path and works whether or not the player rolls now.
		local gold = GameConfig.Roll.GoldCost * reward.Rolls
		CurrencyService.addGold(player, profile, gold)
		table.insert(parts, `{reward.Rolls} free rolls`)
	end

	DataService.markDirty(player)
	SyncService.push(player)

	local summary = if #parts > 0 then table.concat(parts, ", ") else "a reward"
	return { ok = true, data = { summary = summary } }
end

return CodeService
