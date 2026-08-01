--!strict
--[[
	Mutations.luau

	A cosmetic-plus-stat variant rolled independently of the unit and its trait.
	Mutations tint the unit model and multiply its stat line. Two units must share
	the same mutation to be merged (see UnitService.merge), which makes a mutated
	copy meaningfully harder to level than a plain one.

	Mutation Events (see GameConfig.MutationEvent) temporarily inflate the odds
	server-wide, which is what drives the "Mutation Events start every 15 minutes"
	hint in the reference.
]]

export type MutationId = string

export type Mutation = {
	Id: MutationId,
	Display: string,
	Weight: number,
	Damage: number,
	Health: number,
	Cash: number,
	Color: Color3,
	-- Applied to the unit model's material for a quick visual read.
	Material: Enum.Material,
	Glow: number,
}

local Mutations = {}

Mutations.Data = {
	None = {
		Id = "None",
		Display = "Normal",
		Weight = 8600,
		Damage = 1,
		Health = 1,
		Cash = 1,
		Color = Color3.fromRGB(255, 255, 255),
		Material = Enum.Material.SmoothPlastic,
		Glow = 0,
	},
	Gold = {
		Id = "Gold",
		Display = "Gold",
		Weight = 900,
		Damage = 1.25,
		Health = 1.15,
		Cash = 1.35,
		Color = Color3.fromRGB(255, 205, 74),
		Material = Enum.Material.Metal,
		Glow = 0.25,
	},
	Frozen = {
		Id = "Frozen",
		Display = "Frozen",
		Weight = 380,
		Damage = 1.45,
		Health = 1.30,
		Cash = 1.10,
		Color = Color3.fromRGB(140, 226, 255),
		Material = Enum.Material.Ice,
		Glow = 0.4,
	},
	Diamond = {
		Id = "Diamond",
		Display = "Diamond",
		Weight = 105,
		Damage = 1.80,
		Health = 1.60,
		Cash = 1.25,
		Color = Color3.fromRGB(190, 244, 255),
		Material = Enum.Material.Glass,
		Glow = 0.6,
	},
	Void = {
		Id = "Void",
		Display = "Void",
		Weight = 24,
		Damage = 2.40,
		Health = 1.90,
		Cash = 1.45,
		Color = Color3.fromRGB(118, 62, 200),
		Material = Enum.Material.Neon,
		Glow = 0.85,
	},
	Celestial = {
		Id = "Celestial",
		Display = "Celestial",
		Weight = 4,
		Damage = 3.60,
		Health = 2.60,
		Cash = 1.80,
		Color = Color3.fromRGB(255, 250, 205),
		Material = Enum.Material.Neon,
		Glow = 1,
	},
} :: { [MutationId]: Mutation }

Mutations.Order = { "None", "Gold", "Frozen", "Diamond", "Void", "Celestial" } :: { MutationId }

function Mutations.get(id: MutationId?): Mutation
	if id == nil then
		return Mutations.Data.None
	end
	return Mutations.Data[id] or Mutations.Data.None
end

function Mutations.isMutated(id: MutationId?): boolean
	return id ~= nil and id ~= "None"
end

return Mutations
