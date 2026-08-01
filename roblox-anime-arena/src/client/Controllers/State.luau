--!strict
--[[
	State.luau

	Client-side mirror of server truth, plus a tiny observer bus.

	Nothing here is authoritative. Controllers read this to draw, and call
	State.request(...) to ask the server to change something. The server's reply
	(and the ProfileUpdated push that follows) is what actually updates the store.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Net = require(Shared.Net)
local Types = require(Shared.Types)

local State = {}

State.profile = nil :: Types.ProfileSnapshot?
State.shop = nil :: Types.ShopState?
State.bases = {} :: { Types.BaseInfo }
State.myBaseIndex = nil :: number?
State.mutationEventEndsAt = 0

--------------------------------------------------------------------------------
-- Observers
--------------------------------------------------------------------------------

type Listener = () -> ()

local listeners: { [string]: { Listener } } = {}

function State.on(event: string, listener: Listener): () -> ()
	local bucket = listeners[event]
	if not bucket then
		bucket = {}
		listeners[event] = bucket
	end
	table.insert(bucket, listener)

	return function()
		local current = listeners[event]
		if not current then
			return
		end
		local index = table.find(current, listener)
		if index then
			table.remove(current, index)
		end
	end
end

function State.emit(event: string)
	local bucket = listeners[event]
	if not bucket then
		return
	end
	-- Iterate a copy: a listener may unsubscribe itself while we are notifying.
	for _, listener in table.clone(bucket) do
		local ok, err = pcall(listener)
		if not ok then
			warn(`[State] listener for "{event}" errored: {err}`)
		end
	end
end

--------------------------------------------------------------------------------
-- Requests
--------------------------------------------------------------------------------

--[[
	Invoke a server RemoteFunction and normalise the reply.

	A RemoteFunction invocation can throw if the server errors or the player is
	disconnecting, so every call is wrapped. Callers always get a Result table.
]]
function State.request(remoteName: string, ...): Types.Result<any>
	local ok, result = pcall(function(...)
		return Net.func(remoteName):InvokeServer(...)
	end, ...)

	if not ok then
		warn(`[State] request "{remoteName}" failed: {result}`)
		return { ok = false, err = "Connection problem. Try again." }
	end
	if type(result) ~= "table" then
		return { ok = false, err = "Unexpected reply from server." }
	end
	return result
end

--------------------------------------------------------------------------------
-- Derived reads
--------------------------------------------------------------------------------

function State.gold(): number
	local profile = State.profile
	return if profile then profile.Gold else 0
end

function State.gems(): number
	local profile = State.profile
	return if profile then profile.Gems else 0
end

function State.item(itemId: string): number
	local profile = State.profile
	if not profile then
		return 0
	end
	return profile.Items[itemId] or 0
end

function State.ownedUnit(uid: string): Types.OwnedUnit?
	local profile = State.profile
	if not profile then
		return nil
	end
	for _, owned in profile.Inventory do
		if owned.Uid == uid then
			return owned
		end
	end
	return nil
end

function State.myBase(): Types.BaseInfo?
	local index = State.myBaseIndex
	if not index then
		return nil
	end
	for _, base in State.bases do
		if base.Index == index then
			return base
		end
	end
	return nil
end

--------------------------------------------------------------------------------
-- Ingest
--------------------------------------------------------------------------------

function State.setProfile(snapshot: Types.ProfileSnapshot)
	State.profile = snapshot
	State.emit("profile")
end

function State.setShop(shop: Types.ShopState)
	State.shop = shop
	State.emit("shop")
end

function State.setBases(bases: { Types.BaseInfo }, localUserId: number)
	State.bases = bases
	for _, base in bases do
		if base.OwnerUserId == localUserId then
			State.myBaseIndex = base.Index
			break
		end
	end
	State.emit("bases")
end

function State.updateBase(info: Types.BaseInfo, localUserId: number)
	local replaced = false
	for index, base in State.bases do
		if base.Index == info.Index then
			State.bases[index] = info
			replaced = true
			break
		end
	end
	if not replaced then
		table.insert(State.bases, info)
	end

	if info.OwnerUserId == localUserId then
		State.myBaseIndex = info.Index
	elseif State.myBaseIndex == info.Index then
		-- We lost this base (left, or the grace window expired).
		State.myBaseIndex = nil
	end

	State.emit("bases")
end

return State
