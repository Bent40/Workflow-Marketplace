--!strict
--[[
	InventoryController.luau

	The ANIMES panel: the owned-unit grid on the left, the selected unit's detail
	pane on the right (stats, trait, and the sell / lock / merge / reroll / deploy
	actions).

	Stats shown here come from the same StatMath the server uses for damage, so a
	tooltip can never promise a number the unit does not deliver.
]]

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local GameConfig = require(Shared.Config.GameConfig)
local Mutations = require(Shared.Config.Mutations)
local Rarities = require(Shared.Config.Rarities)
local StatMath = require(Shared.Util.StatMath)
local Traits = require(Shared.Config.Traits)
local Types = require(Shared.Types)
local Units = require(Shared.Config.Units)

local Theme = require(script.Parent.Parent.UI.Theme)
local Widgets = require(script.Parent.Parent.UI.Widgets)
local PanelManager = require(script.Parent.PanelManager)
local State = require(script.Parent.State)

local InventoryController = {}

local grid: ScrollingFrame
local detail: Frame
local capacityLabel: TextLabel
local selectedUid: string? = nil

-- Set by init; lets the panel hand a unit to the placement flow.
local onDeployRequested: ((string) -> ())? = nil

local function hud()
	return require(script.Parent.HudController)
end

--------------------------------------------------------------------------------
-- Detail pane
--------------------------------------------------------------------------------

local function clearDetail()
	detail:ClearAllChildren()
	Widgets.padding(Theme.Padding.Normal, detail)
end

local function buildEmptyDetail()
	clearDetail()
	Widgets.label({
		Text = "Select a unit",
		Size = UDim2.new(1, 0, 0, 24),
		TextColor3 = Theme.Color.TextMuted,
		TextXAlignment = Enum.TextXAlignment.Center,
		Position = UDim2.fromScale(0, 0.45),
	}, detail)
end

--[[
	Find a merge partner: another copy of the same unit at the same level and
	mutation, not locked, not the selection itself.
]]
local function findMergePartner(owned: Types.OwnedUnit): Types.OwnedUnit?
	local profile = State.profile
	if not profile then
		return nil
	end
	for _, candidate in profile.Inventory do
		if
			candidate.Uid ~= owned.Uid
			and candidate.Id == owned.Id
			and candidate.Level == owned.Level
			and candidate.Mutation == owned.Mutation
			and not candidate.Locked
		then
			return candidate
		end
	end
	return nil
end

local function buildDetail(uid: string)
	local owned = State.ownedUnit(uid)
	if not owned then
		buildEmptyDetail()
		return
	end

	local unit = Units.expect(owned.Id)
	local rarity = Rarities.get(unit.Rarity)
	local trait = Traits.get(owned.Trait)
	local mutation = Mutations.get(owned.Mutation)
	local stats = StatMath.compute(owned.Id, owned.Level, owned.Trait, owned.Mutation, nil)

	clearDetail()

	Widgets.label({
		Text = unit.Display,
		Size = UDim2.new(1, 0, 0, 26),
		FontFace = Theme.Font.Heading,
		TextSize = 21,
		TextColor3 = rarity.Color,
	}, detail)

	Widgets.label({
		Text = `{rarity.Display} · {unit.Role} · {unit.Element}`,
		Size = UDim2.new(1, 0, 0, 18),
		Position = UDim2.fromOffset(0, 26),
		TextSize = 13,
		TextColor3 = Theme.Color.TextMuted,
	}, detail)

	Widgets.label({
		Text = `<i>{unit.Blurb}</i>`,
		Size = UDim2.new(1, 0, 0, 32),
		Position = UDim2.fromOffset(0, 46),
		TextSize = 12,
		TextColor3 = Theme.Color.TextDim,
		TextWrapped = true,
	}, detail)

	local statHolder = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 170),
		Position = UDim2.fromOffset(0, 84),
		BackgroundTransparency = 1,
	}, detail)
	Widgets.listLayout({ Padding = UDim.new(0, 1) }, statHolder)

	local rows = {
		{ "Level", `{owned.Level} / {GameConfig.Inventory.MaxUnitLevel}`, Theme.Color.Text },
		{ "Damage", Format.abbreviate(stats.Damage), Theme.Color.Danger },
		{ "Attack Speed", `{string.format("%.2f", stats.AttackSpeed)}/s`, Theme.Color.Text },
		{ "DPS", Format.abbreviate(stats.Damage * stats.AttackSpeed), Theme.Color.Warning },
		{ "Range", `{math.floor(stats.Range)} studs`, Theme.Color.Text },
		{ "Integrity", Format.abbreviate(stats.Health), Theme.Color.Gem },
		{ "Crit", `{Format.percent(stats.CritChance, 0)} / x{string.format("%.2f", stats.CritDamage)}`, Theme.Color.Text },
		{ "Attack", unit.AttackShape, Theme.Color.TextMuted },
		{ "Deploy cost", Format.abbreviate(unit.PlaceCost), Theme.Color.Gold },
	}
	for order, row in rows do
		local built = Widgets.statRow(row[1], row[2], row[3], statHolder)
		built.LayoutOrder = order
	end

	-- Trait block.
	local traitBox = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 78),
		Position = UDim2.fromOffset(0, 262),
		BackgroundColor3 = Theme.Color.Backdrop,
	}, detail)
	Widgets.corner(Theme.Radius.Small, traitBox)
	Widgets.padding(8, traitBox)

	Widgets.label({
		Text = `Trait: {trait.Display}`,
		Size = UDim2.new(1, 0, 0, 18),
		FontFace = Theme.Font.Heading,
		TextSize = 14,
		TextColor3 = Rarities.color(trait.Rarity),
	}, traitBox)

	Widgets.label({
		Text = table.concat(Traits.describe(owned.Trait), "  ·  "),
		Size = UDim2.new(1, 0, 0, 40),
		Position = UDim2.fromOffset(0, 20),
		TextSize = 12,
		TextColor3 = Theme.Color.TextMuted,
		TextWrapped = true,
	}, traitBox)

	if mutation.Id ~= "None" then
		Widgets.label({
			Text = `Mutation: {mutation.Display}`,
			Size = UDim2.new(1, 0, 0, 18),
			Position = UDim2.fromOffset(0, 346),
			TextSize = 13,
			TextColor3 = mutation.Color,
		}, detail)
	end

	--------------------------------------------------------------------------
	-- Actions
	--------------------------------------------------------------------------

	local actions = Widgets.frame({
		Size = UDim2.new(1, 0, 0, 148),
		Position = UDim2.new(0, 0, 1, -148),
		BackgroundTransparency = 1,
	}, detail)
	Widgets.gridLayout({
		CellSize = UDim2.new(0.5, -4, 0, 40),
		CellPadding = UDim2.fromOffset(8, 8),
	}, actions)

	Widgets.button({
		Text = "DEPLOY",
		Color = Theme.Color.Success,
		TextColor = Color3.fromRGB(12, 22, 16),
		TextSize = 15,
		LayoutOrder = 1,
		OnClick = function()
			PanelManager.close()
			if onDeployRequested then
				onDeployRequested(uid)
			end
		end,
	}, actions)

	local shards = State.item("TraitShard")
	local rerollButton = Widgets.button({
		Text = `REROLL TRAIT ({shards})`,
		Color = Theme.Color.Warning,
		TextColor = Color3.fromRGB(28, 20, 6),
		TextSize = 13,
		LayoutOrder = 2,
		OnClick = function()
			local result = State.request("RerollTrait", uid)
			if not result.ok then
				hud().toast("error", result.err or "Reroll failed.")
				return
			end
			local data = result.data :: { previous: string, trait: string, improved: boolean }
			local newTrait = Traits.get(data.trait)
			hud().toast(
				if data.improved then "success" else "info",
				`{Traits.get(data.previous).Display} → {newTrait.Display}`
			)
			buildDetail(uid)
		end,
	}, actions)
	Widgets.setEnabled(rerollButton, shards >= Traits.RerollCost, Theme.Color.Warning)

	local partner = findMergePartner(owned)
	local mergeButton = Widgets.button({
		Text = if partner then "MERGE +1 LVL" else "NO MERGE PAIR",
		Color = Theme.Color.Accent,
		TextSize = 13,
		LayoutOrder = 3,
		OnClick = function()
			if not partner then
				return
			end
			local result = State.request("MergeUnit", partner.Uid, uid)
			if not result.ok then
				hud().toast("error", result.err or "Merge failed.")
				return
			end
			hud().toast("success", `{unit.Display} is now level {(result.data :: any).level}.`)
			InventoryController.refresh()
		end,
	}, actions)
	Widgets.setEnabled(
		mergeButton,
		partner ~= nil and owned.Level < GameConfig.Inventory.MaxUnitLevel,
		Theme.Color.Accent
	)

	Widgets.button({
		Text = if owned.Locked then "🔒 LOCKED" else "🔓 UNLOCKED",
		Color = if owned.Locked then Theme.Color.Raised else Theme.Color.PanelAlt,
		TextSize = 13,
		LayoutOrder = 4,
		OnClick = function()
			local result = State.request("ToggleLock", uid)
			if not result.ok then
				hud().toast("error", result.err or "Could not lock.")
				return
			end
			buildDetail(uid)
		end,
	}, actions)

	local sellButton = Widgets.button({
		Text = "SELL",
		Color = Theme.Color.Danger,
		TextSize = 14,
		LayoutOrder = 5,
		OnClick = function()
			local result = State.request("SellUnit", uid)
			if not result.ok then
				hud().toast("error", result.err or "Sell failed.")
				return
			end
			hud().toast("success", `Sold for {Format.abbreviate((result.data :: any).refund)} gold.`)
			selectedUid = nil
			InventoryController.refresh()
		end,
	}, actions)
	Widgets.setEnabled(sellButton, not owned.Locked, Theme.Color.Danger)
end

--------------------------------------------------------------------------------
-- Grid
--------------------------------------------------------------------------------

local function rebuildGrid()
	local profile = State.profile
	if not profile then
		return
	end

	grid:ClearAllChildren()
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(110, 138),
		CellPadding = UDim2.fromOffset(8, 8),
	}, grid)

	-- Strongest first: the player almost always wants their best units on screen.
	local sorted = table.clone(profile.Inventory)
	table.sort(sorted, function(a, b)
		local pa = StatMath.power(a.Id, a.Level, a.Trait, a.Mutation)
		local pb = StatMath.power(b.Id, b.Level, b.Trait, b.Mutation)
		if pa ~= pb then
			return pa > pb
		end
		return a.Uid < b.Uid
	end)

	for order, owned in sorted do
		local card = Widgets.unitCard({
			UnitId = owned.Id,
			Level = owned.Level,
			Trait = owned.Trait,
			Mutation = owned.Mutation,
			Footer = if owned.Locked then `Lv.{owned.Level} 🔒` else `Lv.{owned.Level}`,
		}, grid)
		card.Size = UDim2.fromOffset(110, 138)
		card.LayoutOrder = order

		if owned.Uid == selectedUid then
			local highlight = card:FindFirstChildWhichIsA("UIStroke")
			if highlight then
				highlight.Thickness = 3.5
				highlight.Color = Theme.Color.Text
			end
		end

		card.Activated:Connect(function()
			selectedUid = owned.Uid
			buildDetail(owned.Uid)
			rebuildGrid()
		end)
	end

	capacityLabel.Text = `Inventory: {profile.InventoryCount} / {profile.InventoryCapacity}`
	capacityLabel.TextColor3 = if profile.InventoryCount >= profile.InventoryCapacity
		then Theme.Color.Danger
		else Theme.Color.TextMuted
end

--------------------------------------------------------------------------------
-- Panel
--------------------------------------------------------------------------------

local function build(content: Frame): () -> ()
	capacityLabel = Widgets.label({
		Text = "Inventory: 0 / 0",
		Size = UDim2.new(0.6, 0, 0, 20),
		TextSize = 14,
		TextColor3 = Theme.Color.TextMuted,
	}, content)

	Widgets.button({
		Text = "EQUIP BEST",
		Size = UDim2.new(0, 130, 0, 30),
		Position = UDim2.new(1, -130, 0, -2),
		Color = Theme.Color.Accent,
		TextSize = 13,
		OnClick = function()
			local result = State.request("EquipBest")
			if result.ok then
				hud().toast("success", `Equipped {(result.data :: any).equipped} units.`)
			else
				hud().toast("error", result.err or "Could not equip.")
			end
		end,
	}, content)

	grid = Widgets.scroll({
		Size = UDim2.new(0.56, 0, 1, -34),
		Position = UDim2.fromOffset(0, 30),
	}, content)
	Widgets.gridLayout({
		CellSize = UDim2.fromOffset(110, 138),
		CellPadding = UDim2.fromOffset(8, 8),
	}, grid)

	detail = Widgets.frame({
		Size = UDim2.new(0.44, -10, 1, -34),
		Position = UDim2.new(0.56, 10, 0, 30),
		BackgroundColor3 = Theme.Color.PanelAlt,
	}, content)
	Widgets.corner(Theme.Radius.Medium, detail)
	Widgets.padding(Theme.Padding.Normal, detail)

	buildEmptyDetail()

	return InventoryController.refresh
end

function InventoryController.refresh()
	if not grid then
		return
	end
	rebuildGrid()
	if selectedUid and State.ownedUnit(selectedUid) then
		buildDetail(selectedUid)
	else
		selectedUid = nil
		buildEmptyDetail()
	end
end

function InventoryController.init(deployCallback: (string) -> ())
	onDeployRequested = deployCallback

	PanelManager.register({
		Name = "Inventory",
		Title = "ANIMES",
		Size = UDim2.fromOffset(760, 560),
		Build = build,
	})

	State.on("profile", function()
		PanelManager.refreshIfOpen("Inventory")
	end)
end

return InventoryController
