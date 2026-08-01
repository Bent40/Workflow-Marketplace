--!strict
--[[
	WeightedPick.luau

	Weighted random selection. Every gacha path in the game funnels through here
	so there is exactly one place to audit the odds.
]]

local WeightedPick = {}

export type Entry<T> = { key: T, weight: number }

--[[
	Pick one key from `entries`. Weights need not be normalised. Entries with a
	weight <= 0 are skipped.

	Returns nil only when every weight is <= 0.
]]
function WeightedPick.pick<T>(entries: { Entry<T> }, rng: Random): T?
	local total = 0
	for _, entry in entries do
		if entry.weight > 0 then
			total += entry.weight
		end
	end
	if total <= 0 then
		return nil
	end

	local roll = rng:NextNumber() * total
	for _, entry in entries do
		if entry.weight > 0 then
			roll -= entry.weight
			if roll <= 0 then
				return entry.key
			end
		end
	end

	-- Floating point can leave a sliver; fall back to the last positive entry.
	for i = #entries, 1, -1 do
		if entries[i].weight > 0 then
			return entries[i].key
		end
	end
	return nil
end

-- Convenience for the common `{ [key] = weight }` shape. Iteration order of a
-- Luau table is unspecified, so keys are sorted first to keep picks reproducible
-- for a given seeded Random.
function WeightedPick.fromMap<T>(map: { [T]: number }, rng: Random): T?
	local entries: { Entry<T> } = {}
	for key, weight in map do
		table.insert(entries, { key = key, weight = weight })
	end
	table.sort(entries, function(a, b)
		return tostring(a.key) < tostring(b.key)
	end)
	return WeightedPick.pick(entries, rng)
end

-- Normalised probability of each key, for odds displays.
function WeightedPick.probabilities<T>(map: { [T]: number }): { [T]: number }
	local total = 0
	for _, weight in map do
		if weight > 0 then
			total += weight
		end
	end

	local out: { [T]: number } = {}
	if total <= 0 then
		return out
	end
	for key, weight in map do
		out[key] = math.max(weight, 0) / total
	end
	return out
end

return WeightedPick
