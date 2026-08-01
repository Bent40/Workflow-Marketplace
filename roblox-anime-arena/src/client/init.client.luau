--!strict
--[[
	init.client.luau

	Client bootstrap. Creates the root ScreenGui, starts every controller, pulls
	the initial snapshot, then subscribes to the server's push events.

	The order matters in one place: PanelManager.init must run before any
	controller registers a panel, and the initial GetSnapshot must land before the
	first refresh so the HUD does not flash placeholder values.
]]

local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Net = require(Shared.Net)
local Types = require(Shared.Types)

local Controllers = script.Controllers
local CollectionController = require(Controllers.CollectionController)
local FxController = require(Controllers.FxController)
local HudController = require(Controllers.HudController)
local InventoryController = require(Controllers.InventoryController)
local PanelManager = require(Controllers.PanelManager)
local PlacementController = require(Controllers.PlacementController)
local RollController = require(Controllers.RollController)
local ShopController = require(Controllers.ShopController)
local State = require(Controllers.State)
local UpgradeController = require(Controllers.UpgradeController)

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

--------------------------------------------------------------------------------
-- Root GUI
--------------------------------------------------------------------------------

local screen = Instance.new("ScreenGui")
screen.Name = "AnimeArena"
screen.ResetOnSpawn = false
screen.IgnoreGuiInset = true
screen.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screen.Parent = playerGui

--------------------------------------------------------------------------------
-- Controllers
--------------------------------------------------------------------------------

PanelManager.init(screen)

HudController.init(screen)
FxController.init(screen)

RollController.init(screen)
ShopController.init()
UpgradeController.init()
CollectionController.init()

InventoryController.init(function(uid)
	PlacementController.begin(screen, uid)
end)

--------------------------------------------------------------------------------
-- Initial snapshot
--------------------------------------------------------------------------------

--[[
	The server may still be loading this player's profile when the client boots,
	so retry rather than starting with an empty HUD. Each failure is a normal
	"still loading" refusal, not an error.
]]
task.spawn(function()
	for attempt = 1, 12 do
		local result = State.request("GetSnapshot")
		if result.ok and result.data then
			local data = result.data
			State.setProfile(data.Profile)
			State.setShop(data.Shop)
			State.setBases(data.Bases, player.UserId)
			State.mutationEventEndsAt = data.MutationEventEndsAt or 0
			return
		end
		task.wait(math.min(0.5 * attempt, 3))
	end
	HudController.toast("error", "Could not load your profile. Try rejoining.")
end)

--------------------------------------------------------------------------------
-- Server pushes
--------------------------------------------------------------------------------

Net.event("ProfileUpdated").OnClientEvent:Connect(function(snapshot: Types.ProfileSnapshot)
	State.setProfile(snapshot)
	PanelManager.refreshOpen()
end)

Net.event("ShopUpdated").OnClientEvent:Connect(function(shop: Types.ShopState)
	State.setShop(shop)
end)

Net.event("BasesUpdated").OnClientEvent:Connect(function(bases: { Types.BaseInfo })
	State.setBases(bases, player.UserId)
end)

Net.event("BaseUpdated").OnClientEvent:Connect(function(info: Types.BaseInfo)
	State.updateBase(info, player.UserId)
end)

Net.event("Toast").OnClientEvent:Connect(function(kind: string, message: string)
	HudController.toast(kind, message)
end)

Net.event("Announce").OnClientEvent:Connect(function(kind: string, payload: { [string]: any })
	HudController.onAnnounce(kind, payload)
end)

Net.event("UnitFired").OnClientEvent:Connect(function(baseIndex, uid, targetKeys, isCrit)
	FxController.onUnitFired(baseIndex, uid, targetKeys, isCrit)
end)

Net.event("EnemyDied").OnClientEvent:Connect(function(baseIndex, enemyKey, bounty)
	FxController.onEnemyDied(baseIndex, enemyKey, bounty)
end)

Net.event("WaveStarted").OnClientEvent:Connect(function(baseIndex, wave)
	FxController.onWaveStarted(baseIndex, wave)
end)

Net.event("WaveCleared").OnClientEvent:Connect(function(baseIndex, wave, bonus)
	FxController.onWaveCleared(baseIndex, wave, bonus)
end)

Net.event("BaseFell").OnClientEvent:Connect(function(baseIndex, wave)
	FxController.onBaseFell(baseIndex, wave)
end)

--[[
	EnemySpawned / EnemyDamaged carry state the server already reflects in the
	world (parts and their health bars), so the client does not need to act on
	them yet. They are wired here as no-ops so the contract is visible and a
	future client-side prediction layer has an obvious hook.
]]
Net.event("EnemySpawned").OnClientEvent:Connect(function() end)
Net.event("EnemyDamaged").OnClientEvent:Connect(function() end)

--------------------------------------------------------------------------------
-- World interaction
--------------------------------------------------------------------------------

-- Clicking a deployed unit picks it up (when not already placing something).
UserInputService.InputBegan:Connect(function(input, gameProcessed)
	if gameProcessed then
		return
	end
	if PlacementController.isActive() then
		return
	end
	if input.UserInputType == Enum.UserInputType.MouseButton1 then
		PlacementController.tryPickup()
	end
end)

-- Escape closes the open panel when nothing else claims it.
UserInputService.InputBegan:Connect(function(input, gameProcessed)
	if gameProcessed or PlacementController.isActive() then
		return
	end
	if input.KeyCode == Enum.KeyCode.Escape and PanelManager.isOpen() then
		PanelManager.close()
	end
end)

--------------------------------------------------------------------------------
-- Hub prompts
--------------------------------------------------------------------------------

--[[
	The hub pedestals built by MapBuilder each carry a ProximityPrompt. Map the
	pedestal name onto the panel it opens.
]]
local PROMPT_PANELS = {
	SummonAltar = "Roll",
	ShopStall = "Shop",
	TraitMachine = "Inventory",
	UpgradeTerminal = "Upgrades",
}

local ProximityPromptService = game:GetService("ProximityPromptService")
ProximityPromptService.PromptTriggered:Connect(function(prompt, promptPlayer)
	if promptPlayer ~= player then
		return
	end
	local pedestal = prompt.Parent
	if not pedestal then
		return
	end
	local panelName = PROMPT_PANELS[pedestal.Name]
	if panelName then
		PanelManager.open(panelName)
	end
end)

print("[AnimeArena] Client ready.")
