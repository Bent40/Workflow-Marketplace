--!strict
--[[
	Net.luau

	Remote registry. The server creates every remote up front at boot; the client
	waits for the folder and grabs them by name. Nothing else in the codebase
	touches ReplicatedStorage directly, so the wire surface is exactly this list.

	Convention:
	  Events    fire-and-forget, either direction
	  Functions client asks, server answers with a Types.Result
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Net = {}

Net.FolderName = "AnimeArenaNet"

-- Client -> Server requests that expect a Result envelope back.
Net.Functions = {
	"Roll", -- (count: number, currency: "Gold" | "Gems")
	"BuyShopSlot", -- (slotIndex: number)
	"RefreshShop", -- (useGems: boolean)
	"BuyUpgrade", -- (upgradeId: string)
	"PlaceUnit", -- (uid: string, position: Vector3)
	"RemoveUnit", -- (uid: string)
	"SellUnit", -- (uid: string)
	"MergeUnit", -- (sourceUid: string, targetUid: string)
	"RerollTrait", -- (uid: string)
	"ToggleLock", -- (uid: string)
	"EquipBest", -- ()
	"StartWave", -- ()
	"StopWave", -- ()
	"SetAutoWave", -- (enabled: boolean)
	"RedeemCode", -- (code: string)
	"PromptPurchase", -- (productKey: string)
	"GetSnapshot", -- ()
}

-- Server -> Client pushes.
Net.Events = {
	"ProfileUpdated", -- (snapshot: ProfileSnapshot)
	"ShopUpdated", -- (shopState: ShopState)
	"RollResult", -- (results: { RollResult })
	"BaseUpdated", -- (baseInfo: BaseInfo)
	"BasesUpdated", -- (bases: { BaseInfo })
	"EnemySpawned", -- (baseIndex, enemyKey, enemyId, health, pathProgress)
	"EnemyDamaged", -- (baseIndex, enemyKey, health)
	"EnemyDied", -- (baseIndex, enemyKey, bounty)
	"UnitFired", -- (baseIndex, uid, targetKeys, isCrit)
	"WaveStarted", -- (baseIndex, wave, totalEnemies)
	"WaveCleared", -- (baseIndex, wave, bonus)
	"BaseFell", -- (baseIndex, wave)
	"Announce", -- (kind: string, payload: table) - server-wide rare roll feed
	"Toast", -- (kind: "info" | "error" | "success", message: string)
}

local folder: Folder? = nil

local function ensureFolder(): Folder
	if folder and folder.Parent then
		return folder
	end

	if RunService:IsServer() then
		local existing = ReplicatedStorage:FindFirstChild(Net.FolderName)
		if existing then
			folder = existing :: Folder
			return existing :: Folder
		end
		local created = Instance.new("Folder")
		created.Name = Net.FolderName
		created.Parent = ReplicatedStorage
		folder = created
		return created
	end

	local found = ReplicatedStorage:WaitForChild(Net.FolderName, 30)
	assert(found, "Net: remote folder never replicated")
	folder = found :: Folder
	return found :: Folder
end

--[[
	Server-only. Creates every remote listed above. Call once, early in boot,
	before any service starts connecting handlers.
]]
function Net.build()
	assert(RunService:IsServer(), "Net.build is server-only")
	local root = ensureFolder()

	for _, name in Net.Functions do
		if not root:FindFirstChild(name) then
			local remote = Instance.new("RemoteFunction")
			remote.Name = name
			remote.Parent = root
		end
	end

	for _, name in Net.Events do
		if not root:FindFirstChild(name) then
			local remote = Instance.new("RemoteEvent")
			remote.Name = name
			remote.Parent = root
		end
	end
end

function Net.event(name: string): RemoteEvent
	local root = ensureFolder()
	local remote = if RunService:IsServer() then root:FindFirstChild(name) else root:WaitForChild(name, 30)
	assert(remote and remote:IsA("RemoteEvent"), `Net.event: no RemoteEvent named "{name}"`)
	return remote :: RemoteEvent
end

function Net.func(name: string): RemoteFunction
	local root = ensureFolder()
	local remote = if RunService:IsServer() then root:FindFirstChild(name) else root:WaitForChild(name, 30)
	assert(remote and remote:IsA("RemoteFunction"), `Net.func: no RemoteFunction named "{name}"`)
	return remote :: RemoteFunction
end

--------------------------------------------------------------------------------
-- Result helpers
--------------------------------------------------------------------------------

function Net.ok<T>(data: T?): { ok: boolean, data: T? }
	return { ok = true, data = data }
end

function Net.fail(message: string): { ok: boolean, err: string }
	return { ok = false, err = message }
end

return Net
