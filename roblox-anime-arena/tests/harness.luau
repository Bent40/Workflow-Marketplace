--[[
	harness.luau

	Loads the game's pure config/util modules outside Roblox so their maths can be
	tested in CI (or from the terminal with `luau tests/run.luau`).

	It does two things:
	  1. stubs the handful of Roblox globals those modules touch (Color3, Enum,
	     Vector3, Random),
	  2. emulates Roblox's instance-tree `require(script.Parent.X)` by building a
	     table tree that mirrors src/shared and resolving proxies against it.

	Module sources arrive pre-bundled in tests/.sources.luau because the Luau CLI
	sandbox has no `io` library — tests/run.sh generates that file. Only modules
	with no engine dependency are loadable here; anything touching Instance,
	services or RunService is deliberately out of scope.
]]

local SOURCES = require("./.sources")

local Harness = {}

--------------------------------------------------------------------------------
-- Roblox global stubs
--------------------------------------------------------------------------------

local function makeColor3()
	local Color3 = {}
	Color3.__index = Color3

	function Color3.fromRGB(r: number, g: number, b: number)
		return setmetatable({ R = r / 255, G = g / 255, B = b / 255 }, Color3)
	end

	function Color3.new(r, g, b)
		return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, Color3)
	end

	function Color3:Lerp(other, alpha)
		return Color3.new(
			self.R + (other.R - self.R) * alpha,
			self.G + (other.G - self.G) * alpha,
			self.B + (other.B - self.B) * alpha
		)
	end

	return Color3
end

local function makeVector3()
	local Vector3 = {}
	Vector3.__index = Vector3

	function Vector3.new(x, y, z)
		return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, Vector3)
	end

	return Vector3
end

--[[
	Enum stub: any `Enum.Category.Member` access returns a stable sentinel, so
	config tables that store enum values compare correctly without us having to
	enumerate the real engine enums.
]]
local function makeEnum()
	local categories = setmetatable({}, {
		__index = function(categoryTable, categoryName)
			local members = setmetatable({}, {
				__index = function(memberTable, memberName)
					local value = { EnumType = categoryName, Name = memberName }
					rawset(memberTable, memberName, value)
					return value
				end,
			})
			rawset(categoryTable, categoryName, members)
			return members
		end,
	})
	return categories
end

--[[
	Deterministic Random stub. Roblox's Random is a specific PRNG; we only need
	*a* seeded generator with the same surface, since tests assert on
	distributions and determinism rather than exact sequences.
]]
local function makeRandom()
	local Random = {}
	Random.__index = Random

	function Random.new(seed: number?)
		local state = (seed or os.time()) % 2147483647
		if state <= 0 then
			state += 2147483646
		end
		return setmetatable({ _state = state }, Random)
	end

	function Random:_next(): number
		-- Lehmer / MINSTD.
		self._state = (self._state * 16807) % 2147483647
		return self._state / 2147483647
	end

	function Random:NextNumber(min: number?, max: number?): number
		local value = self:_next()
		if min and max then
			return min + value * (max - min)
		end
		return value
	end

	function Random:NextInteger(min: number, max: number): number
		return math.floor(min + self:_next() * (max - min + 1 - 1e-9))
	end

	return Random
end

--------------------------------------------------------------------------------
-- Module tree
--------------------------------------------------------------------------------

-- folderName -> { moduleName }
local LAYOUT = {
	Config = {
		"Rarities",
		"Traits",
		"Mutations",
		"Units",
		"GameConfig",
		"Upgrades",
		"Waves",
		"ShopConfig",
		"Items",
		"Codes",
		"Monetization",
	},
	Util = { "StatMath", "WeightedPick", "Format" },
}

function Harness.load(): { [string]: any }
	local Color3 = makeColor3()
	local Vector3 = makeVector3()
	local Enum = makeEnum()
	local Random = makeRandom()

	-- Build the folder tree first so proxies can reference their parents.
	local shared = { Name = "Shared" }
	local folders: { [string]: any } = {}
	for folderName in LAYOUT do
		local folder = { Name = folderName, Parent = shared }
		folders[folderName] = folder
		shared[folderName] = folder
	end

	-- proxy -> source key, and proxy -> loaded value.
	local keyOf: { [any]: string } = {}
	local valueOf: { [any]: any } = {}
	local loading: { [any]: boolean } = {}

	for folderName, moduleNames in LAYOUT do
		local folder = folders[folderName]
		for _, moduleName in moduleNames do
			local proxy = { Name = moduleName, Parent = folder }
			folder[moduleName] = proxy
			keyOf[proxy] = `{folderName}/{moduleName}`
		end
	end

	local requireShim
	local function loadModule(proxy: any): any
		if valueOf[proxy] ~= nil then
			return valueOf[proxy]
		end
		assert(not loading[proxy], `harness: cyclic require at {proxy.Name}`)
		loading[proxy] = true

		local key = keyOf[proxy]
		assert(key, `harness: no source registered for {tostring(proxy and proxy.Name)}`)

		local source = SOURCES[key]
		assert(source, `harness: tests/.sources.luau has no entry for {key} — run tests/run.sh`)

		-- `export type` is only legal at the top level of a real module; the
		-- wrapper below makes this a function body, so demote the exports.
		source = string.gsub(source, "export type", "type")

		local wrapper = `return function(script, require, Color3, Vector3, Enum, Random)\n{source}\nend`
		local chunk, err = loadstring(wrapper, `@{key}`)
		assert(chunk, `harness: failed to compile {key}: {tostring(err)}`)

		local factory = (chunk :: any)()
		local value = factory(proxy, requireShim, Color3, Vector3, Enum, Random)

		valueOf[proxy] = value
		loading[proxy] = false
		return value
	end

	requireShim = function(target: any): any
		assert(type(target) == "table", "harness: require expects a module proxy")
		return loadModule(target)
	end

	local modules: { [string]: any } = {}
	for folderName, moduleNames in LAYOUT do
		for _, moduleName in moduleNames do
			modules[moduleName] = loadModule(folders[folderName][moduleName])
		end
	end

	modules._Color3 = Color3
	modules._Random = Random
	return modules
end

return Harness
