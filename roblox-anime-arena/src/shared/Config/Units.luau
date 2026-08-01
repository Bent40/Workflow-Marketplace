--!strict
--[[
	Units.luau

	The summonable roster. Every name here is original to this project — we
	deliberately do not use real (or lightly-renamed) anime characters, because
	that is the fastest way to get a Roblox experience taken down.

	Stat conventions
	----------------
	Damage        raw damage per attack at level 1
	Health        contributed to the base's integrity pool when placed (see
	              BaseService). Tanks are the only units that move this number
	              meaningfully, which is what makes them worth a slot.
	AttackSpeed   attacks per second
	Range         studs
	PlaceCost     gold spent to deploy during a run
	MaxCopies     how many of this unit may be on the board at once
	Aura          SUPPORT-only; multiplies allied stats inside Range

	Attack shapes
	-------------
	Single   one target
	Splash   primary target + everything inside SplashRadius
	Circle   everything inside Range, no primary target
	Line     a pierce down the firing axis, width SplashRadius
	Full     the whole track (reserved for the top tiers)
]]

local Rarities = require(script.Parent.Rarities)

export type UnitId = string
export type Role = "DAMAGE" | "TANK" | "SUPPORT" | "AOE"
export type AttackShape = "Single" | "Splash" | "Circle" | "Line" | "Full"

export type Aura = {
	Damage: number?,
	AttackSpeed: number?,
	Range: number?,
	Cash: number?,
}

export type Unit = {
	Id: UnitId,
	Display: string,
	Rarity: Rarities.RarityId,
	Role: Role,
	Element: string,
	Set: string?,

	Damage: number,
	Health: number,
	AttackSpeed: number,
	Range: number,
	AttackShape: AttackShape,
	SplashRadius: number?,
	CritChance: number,
	CritDamage: number,

	PlaceCost: number,
	MaxCopies: number,
	Aura: Aura?,

	-- Weight *within* its rarity bucket. The rarity is picked first, then one
	-- unit is drawn from that bucket using these weights.
	Weight: number,
	Color: Color3,
	Blurb: string,
}

local Units = {}

local function unit(data: Unit): Unit
	return data
end

Units.Data = {
	--------------------------------------------------------------------------
	-- Common
	--------------------------------------------------------------------------
	Sparrowclad = unit({
		Id = "Sparrowclad",
		Display = "Sparrowclad",
		Rarity = "Common",
		Role = "DAMAGE",
		Element = "Wind",
		Damage = 12,
		Health = 40,
		AttackSpeed = 1.1,
		Range = 22,
		AttackShape = "Single",
		CritChance = 0.05,
		CritDamage = 1.5,
		PlaceCost = 250,
		MaxCopies = 6,
		Weight = 100,
		Color = Color3.fromRGB(168, 200, 220),
		Blurb = "A courier who never put the sword down.",
	}),
	Emberpaw = unit({
		Id = "Emberpaw",
		Display = "Emberpaw",
		Rarity = "Common",
		Role = "AOE",
		Element = "Fire",
		Damage = 9,
		Health = 38,
		AttackSpeed = 0.85,
		Range = 18,
		AttackShape = "Splash",
		SplashRadius = 7,
		CritChance = 0.05,
		CritDamage = 1.5,
		PlaceCost = 300,
		MaxCopies = 6,
		Weight = 100,
		Color = Color3.fromRGB(228, 128, 78),
		Blurb = "Small, warm, and a genuine fire hazard.",
	}),
	Tinlash = unit({
		Id = "Tinlash",
		Display = "Tinlash",
		Rarity = "Common",
		Role = "DAMAGE",
		Element = "Metal",
		Damage = 15,
		Health = 44,
		AttackSpeed = 0.75,
		Range = 20,
		AttackShape = "Single",
		CritChance = 0.08,
		CritDamage = 1.5,
		PlaceCost = 300,
		MaxCopies = 6,
		Weight = 100,
		Color = Color3.fromRGB(180, 184, 190),
		Blurb = "Scrap-metal whip. Surprisingly effective.",
	}),
	Duskrunner = unit({
		Id = "Duskrunner",
		Display = "Duskrunner",
		Rarity = "Common",
		Role = "DAMAGE",
		Element = "Shadow",
		Damage = 8,
		Health = 34,
		AttackSpeed = 1.7,
		Range = 19,
		AttackShape = "Single",
		CritChance = 0.10,
		CritDamage = 1.6,
		PlaceCost = 320,
		MaxCopies = 6,
		Weight = 90,
		Color = Color3.fromRGB(112, 106, 148),
		Blurb = "Hits fast enough that nobody counts.",
	}),
	GravelMonk = unit({
		Id = "GravelMonk",
		Display = "Gravel Monk",
		Rarity = "Common",
		Role = "TANK",
		Element = "Earth",
		Damage = 6,
		Health = 180,
		AttackSpeed = 0.6,
		Range = 14,
		AttackShape = "Splash",
		SplashRadius = 6,
		CritChance = 0.02,
		CritDamage = 1.4,
		PlaceCost = 280,
		MaxCopies = 4,
		Weight = 80,
		Color = Color3.fromRGB(150, 140, 122),
		Blurb = "Meditates directly in the enemy's path.",
	}),
	ReedSentinel = unit({
		Id = "ReedSentinel",
		Display = "Reed Sentinel",
		Rarity = "Common",
		Role = "SUPPORT",
		Element = "Nature",
		Damage = 4,
		Health = 60,
		AttackSpeed = 0.5,
		Range = 26,
		AttackShape = "Single",
		CritChance = 0,
		CritDamage = 1.3,
		PlaceCost = 350,
		MaxCopies = 3,
		Aura = { Damage = 1.06 },
		Weight = 70,
		Color = Color3.fromRGB(126, 178, 120),
		Blurb = "Keeps the line steady. Mostly by staring.",
	}),

	--------------------------------------------------------------------------
	-- Rare
	--------------------------------------------------------------------------
	Kitsara = unit({
		Id = "Kitsara",
		Display = "Kitsara",
		Rarity = "Rare",
		Role = "DAMAGE",
		Element = "Fire",
		Set = "Foxfire",
		Damage = 34,
		Health = 70,
		AttackSpeed = 1.2,
		Range = 26,
		AttackShape = "Single",
		CritChance = 0.12,
		CritDamage = 1.7,
		PlaceCost = 900,
		MaxCopies = 5,
		Weight = 100,
		Color = Color3.fromRGB(240, 142, 96),
		Blurb = "Nine tails, one very short temper.",
	}),
	Voltmaw = unit({
		Id = "Voltmaw",
		Display = "Voltmaw",
		Rarity = "Rare",
		Role = "AOE",
		Element = "Storm",
		Damage = 26,
		Health = 68,
		AttackSpeed = 1.0,
		Range = 24,
		AttackShape = "Line",
		SplashRadius = 5,
		CritChance = 0.10,
		CritDamage = 1.6,
		PlaceCost = 1100,
		MaxCopies = 5,
		Weight = 95,
		Color = Color3.fromRGB(120, 176, 255),
		Blurb = "Chains lightning down the whole lane.",
	}),
	Ironbloom = unit({
		Id = "Ironbloom",
		Display = "Ironbloom",
		Rarity = "Rare",
		Role = "TANK",
		Element = "Metal",
		Damage = 18,
		Health = 520,
		AttackSpeed = 0.7,
		Range = 16,
		AttackShape = "Splash",
		SplashRadius = 8,
		CritChance = 0.04,
		CritDamage = 1.4,
		PlaceCost = 1000,
		MaxCopies = 4,
		Weight = 90,
		Color = Color3.fromRGB(158, 168, 178),
		Blurb = "Armour that grows like a flower. Slowly.",
	}),
	Nightseal = unit({
		Id = "Nightseal",
		Display = "Nightseal",
		Rarity = "Rare",
		Role = "SUPPORT",
		Element = "Shadow",
		Damage = 12,
		Health = 90,
		AttackSpeed = 0.6,
		Range = 30,
		AttackShape = "Single",
		CritChance = 0,
		CritDamage = 1.3,
		PlaceCost = 1200,
		MaxCopies = 3,
		Aura = { Damage = 1.12, AttackSpeed = 1.05 },
		Weight = 80,
		Color = Color3.fromRGB(96, 88, 140),
		Blurb = "Binds the field so nothing lands clean.",
	}),
	Pyrelark = unit({
		Id = "Pyrelark",
		Display = "Pyrelark",
		Rarity = "Rare",
		Role = "AOE",
		Element = "Fire",
		Set = "Foxfire",
		Damage = 22,
		Health = 62,
		AttackSpeed = 1.35,
		Range = 21,
		AttackShape = "Splash",
		SplashRadius = 9,
		CritChance = 0.12,
		CritDamage = 1.65,
		PlaceCost = 1150,
		MaxCopies = 5,
		Weight = 85,
		Color = Color3.fromRGB(255, 164, 110),
		Blurb = "Drops burning feathers on a wide arc.",
	}),

	--------------------------------------------------------------------------
	-- Epic
	--------------------------------------------------------------------------
	Sablefang = unit({
		Id = "Sablefang",
		Display = "Sablefang",
		Rarity = "Epic",
		Role = "DAMAGE",
		Element = "Shadow",
		Set = "Duskpact",
		Damage = 96,
		Health = 140,
		AttackSpeed = 1.45,
		Range = 28,
		AttackShape = "Single",
		CritChance = 0.18,
		CritDamage = 1.9,
		PlaceCost = 3200,
		MaxCopies = 5,
		Weight = 100,
		Color = Color3.fromRGB(86, 74, 118),
		Blurb = "Single-target deletion, no follow-up needed.",
	}),
	Aurorin = unit({
		Id = "Aurorin",
		Display = "Aurorin",
		Rarity = "Epic",
		Role = "SUPPORT",
		Element = "Light",
		Damage = 40,
		Health = 180,
		AttackSpeed = 0.7,
		Range = 34,
		AttackShape = "Single",
		CritChance = 0.05,
		CritDamage = 1.5,
		PlaceCost = 3600,
		MaxCopies = 3,
		Aura = { Damage = 1.22, AttackSpeed = 1.10, Range = 1.10 },
		Weight = 85,
		Color = Color3.fromRGB(255, 236, 168),
		Blurb = "Everyone in the light hits harder.",
	}),
	Grimhelm = unit({
		Id = "Grimhelm",
		Display = "Grimhelm",
		Rarity = "Epic",
		Role = "TANK",
		Element = "Metal",
		Damage = 62,
		Health = 1450,
		AttackSpeed = 0.8,
		Range = 18,
		AttackShape = "Circle",
		SplashRadius = 18,
		CritChance = 0.06,
		CritDamage = 1.5,
		PlaceCost = 3400,
		MaxCopies = 4,
		Weight = 90,
		Color = Color3.fromRGB(120, 126, 140),
		Blurb = "Holds the choke point and asks for more.",
	}),
	StormcallerVey = unit({
		Id = "StormcallerVey",
		Display = "Stormcaller Vey",
		Rarity = "Epic",
		Role = "AOE",
		Element = "Storm",
		Damage = 74,
		Health = 130,
		AttackSpeed = 0.95,
		Range = 30,
		AttackShape = "Splash",
		SplashRadius = 13,
		CritChance = 0.15,
		CritDamage = 1.8,
		PlaceCost = 3800,
		MaxCopies = 5,
		Weight = 95,
		Color = Color3.fromRGB(140, 190, 255),
		Blurb = "Calls the weather down on a crowd.",
	}),
	LotusWarden = unit({
		Id = "LotusWarden",
		Display = "Lotus Warden",
		Rarity = "Epic",
		Role = "SUPPORT",
		Element = "Nature",
		Damage = 34,
		Health = 260,
		AttackSpeed = 0.6,
		Range = 32,
		AttackShape = "Single",
		CritChance = 0,
		CritDamage = 1.4,
		PlaceCost = 3500,
		MaxCopies = 3,
		Aura = { Cash = 1.20, Damage = 1.08 },
		Weight = 75,
		Color = Color3.fromRGB(150, 196, 160),
		Blurb = "Turns a good defence into a good payday.",
	}),

	--------------------------------------------------------------------------
	-- Legendary
	--------------------------------------------------------------------------
	Ravenmoor = unit({
		Id = "Ravenmoor",
		Display = "Ravenmoor",
		Rarity = "Legendary",
		Role = "DAMAGE",
		Element = "Shadow",
		Set = "Duskpact",
		Damage = 420,
		Health = 320,
		AttackSpeed = 1.6,
		Range = 34,
		AttackShape = "Single",
		CritChance = 0.25,
		CritDamage = 2.1,
		PlaceCost = 12000,
		MaxCopies = 4,
		Weight = 100,
		Color = Color3.fromRGB(74, 62, 104),
		Blurb = "The quiet one at the end of the lane.",
	}),
	Solvane = unit({
		Id = "Solvane",
		Display = "Solvane",
		Rarity = "Legendary",
		Role = "AOE",
		Element = "Light",
		Damage = 300,
		Health = 300,
		AttackSpeed = 1.1,
		Range = 36,
		AttackShape = "Circle",
		SplashRadius = 36,
		CritChance = 0.20,
		CritDamage = 2.0,
		PlaceCost = 14000,
		MaxCopies = 4,
		Weight = 95,
		Color = Color3.fromRGB(255, 224, 140),
		Blurb = "Detonates the ring. Everything in it, every time.",
	}),
	AshkeeperRin = unit({
		Id = "AshkeeperRin",
		Display = "Ashkeeper Rin",
		Rarity = "Legendary",
		Role = "SUPPORT",
		Element = "Fire",
		Set = "Foxfire",
		Damage = 180,
		Health = 480,
		AttackSpeed = 0.8,
		Range = 40,
		AttackShape = "Splash",
		SplashRadius = 12,
		CritChance = 0.12,
		CritDamage = 1.8,
		PlaceCost = 13000,
		MaxCopies = 3,
		Aura = { Damage = 1.35, AttackSpeed = 1.15, Cash = 1.15 },
		Weight = 85,
		Color = Color3.fromRGB(236, 150, 92),
		Blurb = "Keeps the embers alive between waves.",
	}),
	Titanhollow = unit({
		Id = "Titanhollow",
		Display = "Titanhollow",
		Rarity = "Legendary",
		Role = "TANK",
		Element = "Earth",
		Damage = 240,
		Health = 6200,
		AttackSpeed = 0.7,
		Range = 22,
		AttackShape = "Circle",
		SplashRadius = 22,
		CritChance = 0.08,
		CritDamage = 1.6,
		PlaceCost = 13500,
		MaxCopies = 3,
		Weight = 85,
		Color = Color3.fromRGB(132, 118, 98),
		Blurb = "A wall that hits back.",
	}),
	MirrorbladeSu = unit({
		Id = "MirrorbladeSu",
		Display = "Mirrorblade Su",
		Rarity = "Legendary",
		Role = "DAMAGE",
		Element = "Light",
		Damage = 260,
		Health = 280,
		AttackSpeed = 2.2,
		Range = 30,
		AttackShape = "Line",
		SplashRadius = 6,
		CritChance = 0.35,
		CritDamage = 2.2,
		PlaceCost = 14500,
		MaxCopies = 4,
		Weight = 80,
		Color = Color3.fromRGB(214, 240, 255),
		Blurb = "Cuts the lane in half, twice a second.",
	}),

	--------------------------------------------------------------------------
	-- Mythic
	--------------------------------------------------------------------------
	Nullspire = unit({
		Id = "Nullspire",
		Display = "Nullspire",
		Rarity = "Mythic",
		Role = "AOE",
		Element = "Void",
		Set = "Nullrite",
		Damage = 1650,
		Health = 900,
		AttackSpeed = 1.2,
		Range = 44,
		AttackShape = "Circle",
		SplashRadius = 44,
		CritChance = 0.28,
		CritDamage = 2.4,
		PlaceCost = 45000,
		MaxCopies = 3,
		Weight = 100,
		Color = Color3.fromRGB(122, 78, 210),
		Blurb = "A hole in the map that charges rent.",
	}),
	Kaijirou = unit({
		Id = "Kaijirou",
		Display = "Kaijirou",
		Rarity = "Mythic",
		Role = "TANK",
		Element = "Earth",
		Damage = 1200,
		Health = 26000,
		AttackSpeed = 0.75,
		Range = 26,
		AttackShape = "Splash",
		SplashRadius = 20,
		CritChance = 0.15,
		CritDamage = 2.0,
		PlaceCost = 46000,
		MaxCopies = 2,
		Weight = 95,
		Color = Color3.fromRGB(96, 132, 108),
		Blurb = "The reason the base still has a floor.",
	}),
	EclipseVow = unit({
		Id = "EclipseVow",
		Display = "Eclipse Vow",
		Rarity = "Mythic",
		Role = "DAMAGE",
		Element = "Shadow",
		Set = "Duskpact",
		Damage = 2400,
		Health = 800,
		AttackSpeed = 1.5,
		Range = 40,
		AttackShape = "Single",
		CritChance = 0.42,
		CritDamage = 2.8,
		PlaceCost = 48000,
		MaxCopies = 3,
		Weight = 90,
		Color = Color3.fromRGB(58, 48, 86),
		Blurb = "Promised someone it would end quickly.",
	}),
	ThornqueenIly = unit({
		Id = "ThornqueenIly",
		Display = "Thornqueen Ily",
		Rarity = "Mythic",
		Role = "SUPPORT",
		Element = "Nature",
		Damage = 900,
		Health = 1600,
		AttackSpeed = 0.9,
		Range = 48,
		AttackShape = "Splash",
		SplashRadius = 16,
		CritChance = 0.20,
		CritDamage = 2.1,
		PlaceCost = 47000,
		MaxCopies = 2,
		Aura = { Damage = 1.60, AttackSpeed = 1.25, Range = 1.15, Cash = 1.30 },
		Weight = 80,
		Color = Color3.fromRGB(180, 110, 160),
		Blurb = "The whole garden fights for her.",
	}),

	--------------------------------------------------------------------------
	-- Secret
	--------------------------------------------------------------------------
	Zerothorn = unit({
		Id = "Zerothorn",
		Display = "Zerothorn",
		Rarity = "Secret",
		Role = "DAMAGE",
		Element = "Void",
		Set = "Nullrite",
		Damage = 14500,
		Health = 3200,
		AttackSpeed = 1.8,
		Range = 46,
		AttackShape = "Line",
		SplashRadius = 10,
		CritChance = 0.45,
		CritDamage = 3.0,
		PlaceCost = 160000,
		MaxCopies = 2,
		Weight = 100,
		Color = Color3.fromRGB(64, 240, 214),
		Blurb = "Was never supposed to leave the index.",
	}),
	HollowChoir = unit({
		Id = "HollowChoir",
		Display = "Hollow Choir",
		Rarity = "Secret",
		Role = "AOE",
		Element = "Void",
		Set = "Nullrite",
		Damage = 9800,
		Health = 4200,
		AttackSpeed = 1.1,
		Range = 60,
		AttackShape = "Full",
		CritChance = 0.32,
		CritDamage = 2.6,
		PlaceCost = 175000,
		MaxCopies = 1,
		Weight = 85,
		Color = Color3.fromRGB(40, 200, 190),
		Blurb = "Sings once. The whole track hears it.",
	}),
	Riftmother = unit({
		Id = "Riftmother",
		Display = "Riftmother",
		Rarity = "Secret",
		Role = "SUPPORT",
		Element = "Void",
		Damage = 6400,
		Health = 8800,
		AttackSpeed = 1.0,
		Range = 70,
		AttackShape = "Splash",
		SplashRadius = 22,
		CritChance = 0.30,
		CritDamage = 2.5,
		PlaceCost = 170000,
		MaxCopies = 1,
		Aura = { Damage = 2.20, AttackSpeed = 1.40, Range = 1.30, Cash = 1.60 },
		Weight = 70,
		Color = Color3.fromRGB(96, 232, 255),
		Blurb = "Opens the door and holds it for everyone.",
	}),

	--------------------------------------------------------------------------
	-- God
	--------------------------------------------------------------------------
	TheUnwritten = unit({
		Id = "TheUnwritten",
		Display = "The Unwritten",
		Rarity = "God",
		Role = "DAMAGE",
		Element = "Origin",
		Damage = 96000,
		Health = 22000,
		AttackSpeed = 2.0,
		Range = 80,
		AttackShape = "Full",
		CritChance = 0.60,
		CritDamage = 3.5,
		PlaceCost = 900000,
		MaxCopies = 1,
		Weight = 100,
		Color = Color3.fromRGB(255, 250, 210),
		Blurb = "No index entry. No counter-play. No notes.",
	}),
	OriginZero = unit({
		Id = "OriginZero",
		Display = "Origin Zero",
		Rarity = "God",
		Role = "SUPPORT",
		Element = "Origin",
		Damage = 42000,
		Health = 60000,
		AttackSpeed = 1.2,
		Range = 90,
		AttackShape = "Circle",
		SplashRadius = 90,
		CritChance = 0.45,
		CritDamage = 3.0,
		PlaceCost = 950000,
		MaxCopies = 1,
		Aura = { Damage = 4.00, AttackSpeed = 1.60, Range = 1.50, Cash = 2.50 },
		Weight = 70,
		Color = Color3.fromRGB(255, 255, 255),
		Blurb = "The board plays differently while it is here.",
	}),
} :: { [UnitId]: Unit }

--------------------------------------------------------------------------------
-- Derived lookups (built once at require time)
--------------------------------------------------------------------------------

-- unitId -> true for fast existence checks, and rarity -> ordered bucket.
local byRarity: { [Rarities.RarityId]: { UnitId } } = {}
local bucketWeight: { [Rarities.RarityId]: number } = {}
local allIds: { UnitId } = {}

for id, data in Units.Data do
	assert(id == data.Id, `Units.Data key "{id}" does not match its Id field "{data.Id}"`)
	table.insert(allIds, id)

	local bucket = byRarity[data.Rarity]
	if not bucket then
		bucket = {}
		byRarity[data.Rarity] = bucket
		bucketWeight[data.Rarity] = 0
	end
	table.insert(bucket, id)
	bucketWeight[data.Rarity] += data.Weight
end

for _, bucket in byRarity do
	table.sort(bucket)
end
table.sort(allIds, function(a, b)
	local ua, ub = Units.Data[a], Units.Data[b]
	local oa, ob = Rarities.get(ua.Rarity).Order, Rarities.get(ub.Rarity).Order
	if oa ~= ob then
		return oa < ob
	end
	return ua.Display < ub.Display
end)

Units.All = allIds
Units.ByRarity = byRarity
Units.BucketWeight = bucketWeight
Units.Count = #allIds

function Units.get(id: UnitId): Unit?
	return Units.Data[id]
end

function Units.expect(id: UnitId): Unit
	local data = Units.Data[id]
	assert(data, `Units.expect: unknown unit "{tostring(id)}"`)
	return data
end

function Units.ofRarity(rarity: Rarities.RarityId): { UnitId }
	return byRarity[rarity] or {}
end

-- Set membership, used by IndexService for collection bonuses.
local sets: { [string]: { UnitId } } = {}
for _, id in allIds do
	local setName = Units.Data[id].Set
	if setName then
		local list = sets[setName]
		if not list then
			list = {}
			sets[setName] = list
		end
		table.insert(list, id)
	end
end
Units.Sets = sets

return Units
